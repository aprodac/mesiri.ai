import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Sparkles, Target, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { setStockLevel, setStockLevels, suggestStockLevels, type StockLevelSuggestion, type StockSummaryRow } from '@/lib/materials'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// PRC-47: the minimum a site should hold of an item, on Materials > Stock. A bar of what it holds against the
// minimum, a "Below minimum" chip, an inline editor (minimum, how much to order when below, "suggest from use"),
// and the sheet that suggests minimums for a whole site from its last week's use. Saving goes to the one route the
// Excel import and WhatsApp use too (PUT /materials/stock-levels).

const detail = (err: unknown, fallback: string) => {
  const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

/** What the site holds against its minimum: full green at twice the minimum, orange under it. */
export function MinimumBar({ row, className }: { row: StockSummaryRow; className?: string }) {
  if (!row.min_qty || Number(row.min_qty) <= 0) return null
  const share = Math.max(0, Math.min(1, Number(row.closing) / (Number(row.min_qty) * 2)))
  return (
    <span className={cn('relative block h-1.5 w-full min-w-12 overflow-hidden rounded-full bg-muted', className)} title={`${qty(row.closing)} of a minimum ${qty(row.min_qty)} ${row.unit}`}>
      <span className={cn('absolute inset-y-0 left-0 rounded-full', row.below_min ? 'bg-orange-500' : 'bg-emerald-500')} style={{ width: `${share * 100}%` }} />
      <span className="absolute inset-y-0 left-1/2 w-px bg-foreground/40" aria-hidden="true" />
    </span>
  )
}

export function BelowMinimumChip({ className }: { className?: string }) {
  return <span className={cn('inline-flex shrink-0 items-center rounded-md bg-orange-100 px-1.5 py-0.5 text-[11px] font-semibold text-orange-900 dark:bg-orange-950 dark:text-orange-100', className)}>Below minimum</span>
}

/** Set, change or remove one item's minimum at one site. ``compact``: the table cell's form. */
export function MinimumEditor({ row, onDone, compact }: { row: StockSummaryRow; onDone?: () => void; compact?: boolean }) {
  const queryClient = useQueryClient()
  const [min, setMin] = React.useState(row.min_qty ? qty(row.min_qty) : '')
  const [reorder, setReorder] = React.useState(row.reorder_qty ? qty(row.reorder_qty) : '')
  const [error, setError] = React.useState('')
  const [hint, setHint] = React.useState('')
  const done = () => {
    queryClient.invalidateQueries({ queryKey: ['materials'] })
    onDone?.()
  }
  const save = useMutation({
    mutationFn: (minQty: string) => setStockLevel({ site_id: row.site_id!, material_id: row.material_id, min_qty: minQty, reorder_qty: minQty !== '0' && reorder ? reorder : null }),
    onSuccess: done,
    onError: (err) => setError(detail(err, 'The minimum was not saved.')),
  })
  const suggest = useMutation({
    mutationFn: () => suggestStockLevels(row.site_id!),
    onSuccess: (got) => {
      const mine = got.items.find((i) => i.material_id === row.material_id)
      if (!mine) {
        setHint('Nothing used here in the last 7 days: no suggestion yet.')
        return
      }
      setMin(mine.min_qty)
      setReorder(mine.reorder_qty)
      setHint(`${qty(mine.used_last_week)} ${row.unit} used in 7 days; ${mine.lead_days} days to deliver${mine.supplier ? ` (${mine.supplier})` : ''}.`)
    },
  })
  if (!row.site_id) return null
  const valid = min.trim() !== '' && Number(min) >= 0 && (reorder.trim() === '' || Number(reorder) > 0)
  return (
    <form
      className={cn('flex flex-col gap-2', compact && 'min-w-64')}
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault()
        setError('')
        if (valid) save.mutate(min.trim())
      }}
    >
      <div className="flex items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Minimum ({row.unit})
          <Input autoFocus={compact} inputMode="decimal" value={min} onChange={(e) => setMin(e.target.value)} className="h-9 text-base tabular-nums text-foreground" aria-label={`Minimum ${row.material_name}`} />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs font-semibold text-muted-foreground">
          Order when below
          <Input inputMode="decimal" value={reorder} placeholder={min ? qty(String(Number(min) * 2)) : ''} onChange={(e) => setReorder(e.target.value)} className="h-9 text-base tabular-nums text-foreground" aria-label={`Reorder ${row.material_name}`} />
        </label>
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" className="gap-1.5" disabled={!valid || save.isPending}>
          <Check className="size-3.5" /> {save.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" size="sm" variant="outline" className="gap-1.5" disabled={suggest.isPending} onClick={() => suggest.mutate()}>
          <Sparkles className="size-3.5" /> Suggest from use
        </Button>
        {row.min_qty && (
          <Button type="button" size="sm" variant="ghost" className="text-muted-foreground" disabled={save.isPending} onClick={() => save.mutate('0')}>
            Remove
          </Button>
        )}
        {compact && (
          <Button type="button" size="icon" variant="ghost" className="ml-auto size-8" title="Close" onClick={onDone}>
            <X className="size-4" />
          </Button>
        )}
      </div>
    </form>
  )
}

/** The table cell: the bar and "min 100", or "Set" for the office; a click opens the editor in place. */
export function MinimumCell({ row, canSet }: { row: StockSummaryRow; canSet: boolean }) {
  const [editing, setEditing] = React.useState(false)
  if (!row.site_id) return <td className="px-3 py-2" />
  if (editing) {
    return (
      <td className="px-3 py-2 align-top" onClick={(e) => e.stopPropagation()}>
        <MinimumEditor row={row} compact onDone={() => setEditing(false)} />
      </td>
    )
  }
  const set = !!row.min_qty && Number(row.min_qty) > 0
  return (
    <td className="px-3 py-2" onClick={(e) => { if (canSet) { e.stopPropagation(); setEditing(true) } }}>
      {set ? (
        <span className={cn('flex min-w-24 flex-col gap-1', canSet && 'cursor-text')} title={canSet ? 'Change the minimum' : undefined}>
          <span className="flex items-center justify-between gap-2 text-xs tabular-nums">
            <span className="text-muted-foreground">min {qty(row.min_qty!)}</span>
            {row.below_min && <BelowMinimumChip />}
          </span>
          <MinimumBar row={row} />
        </span>
      ) : canSet ? (
        <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <Target className="size-3.5" /> Set
        </button>
      ) : (
        <span className="text-muted-foreground">—</span>
      )}
    </td>
  )
}

type Pick = StockLevelSuggestion & { on: boolean; min: string; reorder: string }

/** "Suggest minimums" for a site: every item used in the last 7 days, a minimum of a week plus the lead time, ticked
 * where none is set yet; the person changes any figure and saves the ticked ones together. */
export function SuggestMinimumsDialog({ open, onOpenChange, sites, initialSite }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  sites: { value: string; label: string }[]
  initialSite: string
}) {
  const queryClient = useQueryClient()
  const [site, setSite] = React.useState(initialSite)
  const [picks, setPicks] = React.useState<Pick[]>([])
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    if (open) setSite(initialSite || sites[0]?.value || '')
  }, [open, initialSite, sites])
  const got = useQuery({ queryKey: ['materials', 'stock-levels', 'suggest', site], queryFn: () => suggestStockLevels(site), enabled: open && !!site })
  React.useEffect(() => {
    setPicks((got.data?.items ?? []).map((i) => ({ ...i, on: i.current_min === null, min: i.min_qty, reorder: i.reorder_qty })))
  }, [got.data])
  const save = useMutation({
    mutationFn: () => setStockLevels(picks.filter((p) => p.on).map((p) => ({ site_id: p.site_id, material_id: p.material_id, min_qty: p.min, reorder_qty: p.reorder || null, source: 'suggested' as const }))),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      onOpenChange(false)
    },
    onError: (err) => setError(detail(err, 'The minimums were not saved.')),
  })
  const ticked = picks.filter((p) => p.on).length
  const change = (id: string, patch: Partial<Pick>) => setPicks((all) => all.map((p) => (p.material_id === id ? { ...p, ...patch } : p)))
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] gap-3 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Minimum stock from use</DialogTitle>
          <DialogDescription>A week of each item's use plus the days its supplier takes to deliver. Below the minimum, Mesiri tells the office each morning, with a draft request.</DialogDescription>
        </DialogHeader>
        {sites.length > 1 && (
          <select value={site} onChange={(e) => setSite(e.target.value)} className="h-9 rounded-lg border bg-background px-2 text-sm" aria-label="Site">
            {sites.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        )}
        {got.isLoading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Working out the use…</p>
        ) : picks.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Nothing was used at this site in the last 7 days, so there is nothing to suggest from yet. Set a minimum on any item in the list instead.</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {picks.map((p) => (
              <li key={p.material_id} className={cn('flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center', !p.on && 'opacity-60')}>
                <label className="flex min-w-0 flex-1 items-start gap-2.5">
                  <input type="checkbox" checked={p.on} onChange={(e) => change(p.material_id, { on: e.target.checked })} className="mt-1 size-4 accent-yellow-500" />
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{p.material}</span>
                    <span className="block text-xs text-muted-foreground">
                      {qty(p.used_last_week)} {p.unit} used in 7 days · {qty(p.closing)} held · {p.lead_days} days to deliver
                      {p.current_min !== null && <> · now min {qty(p.current_min)}</>}
                    </span>
                  </span>
                </label>
                <span className="flex items-center gap-2 pl-6 sm:pl-0">
                  <Input inputMode="decimal" value={p.min} onChange={(e) => change(p.material_id, { min: e.target.value, on: true })} className="h-9 w-20 text-right tabular-nums" aria-label={`Minimum ${p.material}`} />
                  <span className="text-xs text-muted-foreground">order</span>
                  <Input inputMode="decimal" value={p.reorder} onChange={(e) => change(p.material_id, { reorder: e.target.value, on: true })} className="h-9 w-20 text-right tabular-nums" aria-label={`Reorder ${p.material}`} />
                  <span className="w-10 text-xs text-muted-foreground">{p.unit}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!ticked || save.isPending} onClick={() => { setError(''); save.mutate() }}>
            {save.isPending ? 'Saving…' : `Save ${ticked} ${ticked === 1 ? 'minimum' : 'minimums'}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
