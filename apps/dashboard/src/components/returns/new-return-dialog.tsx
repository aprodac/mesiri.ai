import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, PackageX, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { fileBase64 } from '@/lib/materials'
import { rupees } from '@/lib/orders'
import { REASONS, createReturn, fetchReturnSources, type MaterialReturn, type ReturnFrom, type ReturnReason, type ReturnSource } from '@/lib/returns'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// PRC-46: send material back to the supplier. Started from a GRN's rejected quantity, a delivery in Movements, or the
// supplier's page (their deliveries of the last 90 days); each line: how much, why, at what rate (the delivery's by
// default); photos of the damage. Saving takes it out of stock (what was in stock) and makes the debit note.

type Pick = ReturnSource & { key: string; on: boolean; quantity: string; reason: ReturnReason; rate: string; given: string }

/** "torn bags", "bent", "broken": damaged; the gate's words picked into a reason where they plainly say one. */
function reasonOf(said: string | null | undefined): ReturnReason {
  const s = (said ?? '').toLowerCase()
  if (/size|dia|thick|wrong/.test(s)) return 'wrong_size'
  if (/short|less|weight/.test(s)) return 'short'
  if (/extra|excess|more than/.test(s)) return 'excess'
  if (/test|quality|grade|fail/.test(s)) return 'quality_failed'
  return 'damaged'
}

export function NewReturnDialog({ open, onOpenChange, from, money, onCreated }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  from: ReturnFrom | null
  money: boolean
  onCreated?: (r: MaterialReturn) => void
}) {
  const queryClient = useQueryClient()
  const [picks, setPicks] = React.useState<Pick[]>([])
  const [site, setSite] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [photos, setPhotos] = React.useState<File[]>([])
  const [error, setError] = React.useState('')
  const sources = useQuery({ queryKey: ['procurement', 'returns', 'sources', from], queryFn: () => fetchReturnSources(from!), enabled: open && !!from })
  React.useEffect(() => {
    if (!open) return
    setNotes('')
    setPhotos([])
    setError('')
  }, [open])
  React.useEffect(() => {
    const items = sources.data ?? []
    const single = !!from && !('vendor_id' in from)
    setPicks(items.map((s, i) => ({ ...s, key: s.grn_line_id ?? s.receipt_id ?? String(i), on: single, quantity: single ? s.left : '', reason: reasonOf(s.said_reason), rate: s.rate ?? '', given: s.rate ?? '' })))
    setSite(items[0]?.site_id ?? '')
  }, [sources.data, from])
  const sites = [...new Map(picks.map((p) => [p.site_id, p.site_name])).entries()]
  const shown = picks.filter((p) => p.site_id === site)
  const chosen = shown.filter((p) => p.on && Number(p.quantity) > 0)
  const vendor = shown[0]?.vendor_id ?? undefined
  const total = chosen.reduce((n, p) => n + Number(p.quantity) * Number(p.rate || 0), 0)
  const change = (key: string, patch: Partial<Pick>) => setPicks((all) => all.map((p) => (p.key === key ? { ...p, ...patch } : p)))
  const save = useMutation({
    mutationFn: async () =>
      createReturn({
        vendor_id: vendor,
        site_id: site,
        notes: notes.trim() || null,
        photos: await Promise.all(photos.map(async (f) => ({ content_type: f.type || 'image/jpeg', data_base64: await fileBase64(f) }))),
        lines: chosen.map((p) => ({
          quantity: p.quantity,
          reason: p.reason,
          ...(p.grn_line_id ? { grn_line_id: p.grn_line_id } : { receipt_id: p.receipt_id }),
          // A rate changed here is sent; otherwise the API takes the delivery's (or the order line's) with its GST.
          ...(money && p.rate && p.rate !== p.given ? { rate: p.rate } : {}),
        })),
      }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      queryClient.invalidateQueries({ queryKey: ['materials'] })
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
      onOpenChange(false)
      onCreated?.(r)
    },
    onError: (err: unknown) => {
      const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof d === 'string' ? d : 'The return was not saved.')
    },
  })
  const tooMuch = chosen.some((p) => Number(p.quantity) > Number(p.left))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] gap-3 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><PackageX className="size-5 text-orange-600" /> Return to supplier</DialogTitle>
          <DialogDescription>
            {shown[0] ? <>To <strong className="text-foreground">{shown[0].vendor_name ?? 'the supplier'}</strong> from {shown[0].site_name}. </> : null}
            What was in stock leaves it; the debit note lowers what you owe them at once.
          </DialogDescription>
        </DialogHeader>
        {sites.length > 1 && (
          <select value={site} onChange={(e) => setSite(e.target.value)} className="h-9 rounded-lg border bg-background px-2 text-sm" aria-label="Site">
            {sites.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        )}
        {sources.isLoading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Loading what can go back…</p>
        ) : shown.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Nothing here is left to send back: it is already on a return, or nothing came from this supplier in the last 90 days.</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {shown.map((p) => (
              <li key={p.key} className={cn('flex flex-col gap-2 px-3 py-3', !p.on && 'opacity-70')}>
                <label className="flex items-start gap-2.5">
                  <input type="checkbox" checked={p.on} onChange={(e) => change(p.key, { on: e.target.checked, quantity: e.target.checked && !p.quantity ? p.left : p.quantity })} className="mt-1 size-4 accent-yellow-500" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{p.material}</span>
                    <span className="block text-xs text-muted-foreground">
                      {p.grn_line_id ? `${p.from}: ${qty(p.left)} ${p.unit} rejected at the gate${p.said_reason ? ` (${p.said_reason})` : ''}, not in stock` : `Delivered ${p.date}: ${qty(p.delivered ?? p.left)} ${p.unit}, ${qty(p.left)} can go back`}
                    </span>
                  </span>
                </label>
                {p.on && (
                  <div className="grid grid-cols-2 gap-2 pl-6 sm:grid-cols-[7rem_1fr_7rem]">
                    <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
                      Quantity ({p.unit})
                      <Input inputMode="decimal" value={p.quantity} onChange={(e) => change(p.key, { quantity: e.target.value })} className={cn('h-10 text-base tabular-nums text-foreground', Number(p.quantity) > Number(p.left) && 'border-destructive')} />
                    </label>
                    <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
                      Why
                      <select value={p.reason} onChange={(e) => change(p.key, { reason: e.target.value as ReturnReason })} className="h-10 rounded-md border bg-background px-2 text-sm text-foreground">
                        {REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                    </label>
                    {money && (
                      <label className="col-span-2 flex flex-col gap-1 text-xs font-semibold text-muted-foreground sm:col-span-1">
                        Rate (₹ / {p.unit})
                        <Input inputMode="decimal" value={p.rate} onChange={(e) => change(p.key, { rate: e.target.value })} className="h-10 text-base tabular-nums text-foreground" />
                      </label>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
            Note for the supplier (optional)
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Bent bars kept at the gate; collect by Friday" className="text-sm text-foreground" />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-3 text-sm hover:bg-muted/50">
              <Camera className="size-4" /> Add photos
              <input type="file" accept="image/*" multiple className="sr-only" onChange={(e) => setPhotos((all) => [...all, ...Array.from(e.target.files ?? [])].slice(0, 4))} />
            </label>
            {photos.map((f, i) => (
              <span key={i} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs">
                {f.name.slice(0, 18)}
                <button type="button" aria-label="Remove photo" onClick={() => setPhotos((all) => all.filter((_, j) => j !== i))}><X className="size-3" /></button>
              </span>
            ))}
          </div>
        </div>
        {tooMuch && <p className="text-sm text-destructive">More than can go back on a line.</p>}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <span className="text-sm text-muted-foreground">{money && total > 0 ? <>Debit note about <strong className="text-foreground">{rupees(total)}</strong> before GST</> : null}</span>
          <span className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button className="font-semibold" disabled={!chosen.length || tooMuch || save.isPending} onClick={() => { setError(''); save.mutate() }}>
              {save.isPending ? 'Saving…' : `Return ${chosen.length} ${chosen.length === 1 ? 'item' : 'items'}`}
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
