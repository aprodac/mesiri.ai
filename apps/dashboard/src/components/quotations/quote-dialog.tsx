import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { GstField } from '@/components/procurement/gst-field'
import { GST_NOT_SAID, gstPayload, gstSplit, type GstValue } from '@/lib/gst'
import { rupees } from '@/lib/orders'
import { rate } from '@/lib/rates'
import { recordQuote, type Rfq, type RfqSupplier } from '@/lib/rfqs'
import { CategoryTile } from '@/components/requests/parts'

// PRC-42: one supplier's quote, typed from their message or paper: a rate per item (blank = not quoted), the GST the
// quote prints (one for all, as most quotes have), and its terms. A revised quote opens with what they said before and
// replaces it. A forwarded quote photo is read on WhatsApp (the assistant fills this same route).

type Row = { lineId: string; rate: string; brand: string }

export function QuoteDialog({ rfq, supplier, open, onOpenChange }: { rfq: Rfq; supplier: RfqSupplier | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [rows, setRows] = React.useState<Row[]>([])
  const [gst, setGst] = React.useState<GstValue>(GST_NOT_SAID)
  const [delivery, setDelivery] = React.useState('')
  const [payment, setPayment] = React.useState('')
  const [valid, setValid] = React.useState('')
  const [theirRef, setTheirRef] = React.useState('')
  const [notes, setNotes] = React.useState('')
  const [error, setError] = React.useState('')
  const queryClient = useQueryClient()
  const toast = useToast()

  React.useEffect(() => {
    if (!open || !supplier) return
    const mine = (line: Rfq['lines'][number]) => line.quotes.find((q) => q.rfq_vendor_id === supplier.rfq_vendor_id)
    setRows(rfq.lines.map((l) => ({ lineId: l.id, rate: mine(l)?.rate_entered ? String(Number(mine(l)!.rate_entered)) : '', brand: mine(l)?.brand ?? '' })))
    const first = rfq.lines.map(mine).find((q) => q?.gst_percent != null)
    setGst(first ? { percent: String(Number(first.gst_percent)), includes: first.rate_includes_gst ?? null } : GST_NOT_SAID)
    setDelivery(supplier.delivery_days != null ? String(supplier.delivery_days) : '')
    setPayment(supplier.payment_days != null ? String(supplier.payment_days) : '')
    setValid(supplier.valid_until ?? '')
    setTheirRef(supplier.their_ref ?? '')
    setNotes(supplier.notes ?? '')
    setError('')
  }, [open, supplier, rfq])

  const filled = rows.filter((r) => r.rate && Number(r.rate) >= 0)
  const total = filled.reduce((sum, r) => {
    const line = rfq.lines.find((l) => l.id === r.lineId)!
    const s = gstSplit(r.rate, gst)
    return sum + (s ? s.withGst : Number(r.rate)) * Number(line.quantity)
  }, 0)

  const save = useMutation({
    mutationFn: () => recordQuote(rfq.id, {
      vendor_id: supplier!.vendor_id,
      lines: filled.map((r) => ({ rfq_line_id: r.lineId, rate: r.rate, brand: r.brand.trim() || null })),
      ...(() => { const g = gstPayload(gst); return { gst_percent: g.gst_percent, rates_include_gst: g.rate_includes_gst } })(),
      delivery_days: delivery ? Number(delivery) : null,
      payment_days: payment ? Number(payment) : null,
      valid_until: valid || null,
      their_ref: theirRef.trim() || null,
      notes: notes.trim() || null,
    }),
    onSuccess: (r) => {
      queryClient.setQueryData(['procurement', 'rfq', r.id], r)
      queryClient.invalidateQueries({ queryKey: ['procurement'] })
      toast.success(`${supplier!.name}'s quote saved`, r.status === 'ready' ? 'Every supplier has answered: compare and order.' : undefined)
      onOpenChange(false)
    },
    onError: (err) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Not saved. Try again.')
    },
  })

  if (!supplier) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{supplier.status === 'quoted' ? 'Revise' : 'Record'} {supplier.name}'s quote · {rfq.ref}</DialogTitle>
        </DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (filled.length && !save.isPending) save.mutate() }}>
          <div className="flex flex-col divide-y rounded-xl border">
            {rfq.lines.map((line, i) => {
              const row = rows[i]
              if (!row) return null
              const last = line.last_paid
              return (
                <div key={line.id} className="flex flex-col gap-1.5 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <CategoryTile mainCategory={line.main_category} size="sm" />
                    <span className="min-w-0 flex-1"><span className="font-semibold">{line.material}</span> <span className="text-sm text-muted-foreground tabular-nums">{Number(line.quantity).toLocaleString('en-IN')} {line.unit}</span></span>
                    <div className="flex w-40 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                      <span className="pl-2.5 text-sm text-muted-foreground">₹</span>
                      <Input aria-label={`${line.material} rate`} inputMode="decimal" autoFocus={i === 0} className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0" placeholder="Rate" value={row.rate}
                        onChange={(e) => setRows((all) => all.map((r, j) => (j === i ? { ...r, rate: e.target.value.replace(/[^0-9.]/g, '') } : r)))} />
                      <span className="pr-2.5 text-xs text-muted-foreground">/{line.unit}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pl-10">
                    <Input aria-label={`${line.material} brand`} className="h-8 w-44 text-xs" placeholder="Brand (optional)" value={row.brand} maxLength={80}
                      onChange={(e) => setRows((all) => all.map((r, j) => (j === i ? { ...r, brand: e.target.value } : r)))} />
                    {last && <span className="text-xs text-muted-foreground">Last paid {rate(last.rate)}/{line.unit} · {last.vendor_name}</span>}
                  </div>
                </div>
              )
            })}
          </div>
          <p className="-mt-2 text-xs text-muted-foreground">Leave a rate blank when they did not quote that item. Rates per {rfq.lines.length === 1 ? rfq.lines[0].unit : 'each item’s unit'}.</p>

          <div className="rounded-xl border bg-muted/30 p-3">
            <GstField value={gst} onChange={setGst} rate={filled[0]?.rate} unit={rfq.lines.find((l) => l.id === filled[0]?.lineId)?.unit} />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="flex flex-col gap-1.5"><Label htmlFor="q-delivery">Delivery (days)</Label><Input id="q-delivery" inputMode="numeric" value={delivery} placeholder="2" onChange={(e) => setDelivery(e.target.value.replace(/\D/g, ''))} /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor="q-payment">Credit (days)</Label><Input id="q-payment" inputMode="numeric" value={payment} placeholder="30" onChange={(e) => setPayment(e.target.value.replace(/\D/g, ''))} /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor="q-valid">Valid until</Label><Input id="q-valid" type="date" className="dark:[color-scheme:dark]" value={valid} onChange={(e) => setValid(e.target.value)} /></div>
            <div className="flex flex-col gap-1.5"><Label htmlFor="q-ref">Their quote no.</Label><Input id="q-ref" value={theirRef} maxLength={60} onChange={(e) => setTheirRef(e.target.value)} /></div>
          </div>
          <div className="flex flex-col gap-1.5"><Label htmlFor="q-notes">Notes</Label><Input id="q-notes" value={notes} maxLength={500} placeholder="Unloading extra; 50% advance" onChange={(e) => setNotes(e.target.value)} /></div>

          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <DialogFooter className="items-center gap-2 sm:justify-between">
            <span className="text-sm text-muted-foreground">{filled.length ? <>{filled.length} of {rfq.lines.length} quoted · <strong className="text-foreground tabular-nums">{rupees(total)}</strong>{gst.percent && Number(gst.percent) > 0 ? ' with GST' : ''}</> : 'Type at least one rate'}</span>
            <span className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={!filled.length || save.isPending} className="font-semibold">Save quote</Button>
            </span>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
