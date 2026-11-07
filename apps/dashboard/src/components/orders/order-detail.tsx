import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, CalendarDays, Check, ClipboardList, Clock, PackageCheck, Phone, ShoppingCart, Truck, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { cn } from '@/lib/utils'
import { URGENCY_LOOK, qty, swatch } from '@/lib/requests'
import { ORDER_LOOK, cancelOrder, closeOrder, dueWords, receiveOrder, rupees, updateOrder, type PurchaseOrder } from '@/lib/orders'
import { CategoryTile, ProjectDot } from '@/components/requests/parts'

// PRC-06/08: one order, as the office and the site see it: the supplier, what was ordered and what came per line,
// the deliveries so far, the requests it covers, and the next step (receive, move the date, cancel, close short).

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : 'That did not save. Try again.'
}

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function VendorTile({ id, name, size = 'md' }: { id: string; name: string; size?: 'md' | 'lg' }) {
  const colour = swatch(id)
  const letters = name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <span className={cn('inline-flex shrink-0 items-center justify-center rounded-xl font-bold', size === 'lg' ? 'size-12 text-base' : 'size-10 text-sm')} style={{ background: `${colour}1f`, color: colour }} aria-hidden>
      {letters}
    </span>
  )
}

export function OrderProgress({ order, className }: { order: PurchaseOrder; className?: string }) {
  const tone = order.status === 'received' ? 'bg-green-700' : order.status === 'closed' ? 'bg-stone-500' : 'bg-teal-600'
  return (
    <span className={cn('flex h-2.5 overflow-hidden rounded-full bg-blue-100 dark:bg-blue-950', className)} aria-hidden>
      <span className={tone} style={{ width: `${Math.round(order.progress * 100)}%` }} />
    </span>
  )
}

export function OrderDetail({ order, inSheet }: { order: PurchaseOrder; inSheet?: boolean }) {
  const [dialog, setDialog] = React.useState<'receive' | 'cancel' | 'close' | null>(null)
  const [date, setDate] = React.useState(order.expected_date ?? '')
  React.useEffect(() => setDate(order.expected_date ?? ''), [order.id, order.expected_date])
  const queryClient = useQueryClient()
  const toast = useToast()
  const done = (msg: string) => () => {
    queryClient.invalidateQueries({ queryKey: ['procurement'] })
    queryClient.invalidateQueries({ queryKey: ['materials'] })
    setDialog(null)
    toast.success(msg)
  }
  const fail = (err: unknown) => toast.error('Not saved', errorText(err))
  const move = useMutation({ mutationFn: (d: string) => updateOrder(order.id, { expected_date: d || null }), onSuccess: done('Date changed'), onError: fail })
  const open = order.status === 'open' || order.status === 'part'

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 bg-sky-50 px-5 pt-5 pb-4 dark:bg-sky-950/40">
        <div className={cn('flex items-center justify-between gap-2', inSheet && 'pr-8')}>
          <span className="text-xs font-semibold text-muted-foreground tabular-nums">{order.ref}</span>
          <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold', ORDER_LOOK[order.status].chip)}>
            <span className={cn('size-1.5 rounded-full', ORDER_LOOK[order.status].dot)} />{ORDER_LOOK[order.status].label}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <VendorTile id={order.vendor_id} name={order.vendor_name} size="lg" />
          <div className="min-w-0">
            <h2 className="truncate text-xl leading-tight font-semibold">{order.vendor_name}</h2>
            <div className="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
              {order.vendor_phone && <a href={`tel:${order.vendor_phone}`} className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline"><Phone className="size-3.5" />{order.vendor_phone}</a>}
              <span className="inline-flex items-center gap-1.5"><ProjectDot id={order.project_id} />{order.project_name} › {order.site_name}</span>
            </div>
          </div>
        </div>
        {order.value !== null && (
          <div className="text-2xl font-semibold tabular-nums">{rupees(order.value)}{order.value_complete === false && <span className="ml-2 text-xs font-normal text-muted-foreground">some lines have no rate</span>}</div>
        )}
        <div className={cn('flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold', URGENCY_LOOK[order.urgency].chip)}>
          <Clock className="size-4" strokeWidth={2.4} />{dueWords(order)}
        </div>
      </div>

      {order.duplicates.length > 0 && open && (
        <div className="mx-5 mt-4 rounded-lg bg-orange-100 px-3 py-2.5 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
          <strong>Also on order:</strong> {order.duplicates.map((d) => `${d.ref} (${d.vendor_name})`).join(', ')}
        </div>
      )}

      <div className="flex flex-col gap-3 border-b px-5 py-4">
        {order.lines.map((line) => {
          const q = Number(line.quantity) || 1
          const got = Math.min(Number(line.received), q)
          return (
            <div key={line.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <CategoryTile mainCategory={line.main_category} size="sm" />
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{line.material}</span>
                <span className="text-sm tabular-nums">{qty(line.quantity, line.unit)}</span>
                {line.rate && <span className="w-24 text-right text-xs text-muted-foreground tabular-nums">₹{Number(line.rate).toLocaleString('en-IN')}/{line.unit}</span>}
              </div>
              <span className="flex h-2 overflow-hidden rounded-full bg-blue-100 dark:bg-blue-950" aria-hidden>
                <span className="bg-green-700" style={{ width: `${(got / q) * 100}%` }} />
              </span>
              <div className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                <span><strong className="text-success">{qty(line.received, line.unit)}</strong> came</span>
                {Number(line.pending) > 0 && <span><strong className="text-info">{qty(line.pending, line.unit)}</strong> to come</span>}
                {Number(line.extra) > 0 && <span className="font-semibold text-orange-700">{qty(line.extra, line.unit)} extra</span>}
                {line.request && <span className="inline-flex items-center gap-1"><ClipboardList className="size-3" />{line.request.ref}</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-col px-5 py-4">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">History</h3>
        <Step icon={ShoppingCart} title={`Ordered${order.created_by_name ? ` by ${order.created_by_name}` : ''}`} meta={when(order.created_at)} quote={order.notes} />
        {order.deliveries.map((d) => <Step key={d.id} icon={Truck} title={`${qty(d.quantity, d.unit)} ${d.material} came`} meta={`${d.by_name ?? ''} · ${new Date(`${d.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`} />)}
        {order.status === 'received' && <Step icon={PackageCheck} title="Everything came" />}
        {(order.status === 'closed' || order.status === 'cancelled') && <Step icon={order.status === 'cancelled' ? Ban : Check} title={order.status === 'cancelled' ? 'Cancelled' : 'Closed short'} meta={`${order.status_by_name ?? ''}${order.status_at ? ` · ${when(order.status_at)}` : ''}`} quote={order.status_note} bad />}
        {open && <Step icon={Clock} title="Waiting for the rest" now />}
      </div>

      {open && (
        <div className="flex flex-col gap-2 border-t px-5 py-4">
          {order.may_receive && (
            <Button className="h-11 gap-2 font-semibold" onClick={() => setDialog('receive')}><Truck className="size-4" /> Material came</Button>
          )}
          {order.may_edit || order.may_close ? (
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex h-10 items-center gap-2 rounded-md border px-2.5 text-sm">
                <CalendarDays className="size-4 text-muted-foreground" />
                <span className="sr-only">Expected by</span>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} onBlur={() => date !== (order.expected_date ?? '') && move.mutate(date)} className="bg-transparent outline-none dark:[color-scheme:dark]" />
              </label>
              {order.may_cancel && <Button variant="outline" className="h-10 border-destructive/30 text-destructive" onClick={() => setDialog('cancel')}><X className="size-4" /> Cancel order</Button>}
              {order.may_close && <Button variant="outline" className="h-10" onClick={() => setDialog('close')}>Close short</Button>}
            </div>
          ) : null}
        </div>
      )}

      <ReceiveDialog order={order} open={dialog === 'receive'} onClose={() => setDialog(null)} onDone={done('Delivery recorded; stock is updated')} onError={fail} />
      <ReasonDialog
        open={dialog === 'cancel' || dialog === 'close'}
        title={dialog === 'cancel' ? `Cancel ${order.ref}` : `Close ${order.ref} short`}
        hint={dialog === 'cancel' ? 'Its requests go back to waiting.' : 'What came stays; the rest is no longer expected.'}
        placeholder={dialog === 'cancel' ? 'Supplier has no stock' : 'Rest out of stock, ordering elsewhere'}
        onClose={() => setDialog(null)}
        onSave={(reason) => (dialog === 'cancel' ? cancelOrder(order.id, reason) : closeOrder(order.id, reason)).then(done(dialog === 'cancel' ? 'Order cancelled' : 'Order closed'), fail)}
      />
    </div>
  )
}

function Step({ icon: Icon, title, meta, quote, now, bad }: { icon: typeof Clock; title: string; meta?: string; quote?: string | null; now?: boolean; bad?: boolean }) {
  return (
    <div className="flex gap-2.5">
      <span className={cn('mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full', now ? 'border-2 border-yellow-500 bg-yellow-50 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200' : bad ? 'bg-destructive/10 text-destructive' : 'bg-foreground text-background')}>
        <Icon className="size-3" strokeWidth={2.6} />
      </span>
      <div className="min-w-0 pb-3">
        <div className={cn('text-sm', now ? 'font-semibold' : 'font-medium')}>{title}</div>
        {meta && <div className="text-xs text-muted-foreground">{meta}</div>}
        {quote && <div className="mt-1 max-w-xs rounded-xl rounded-bl-sm bg-muted px-3 py-1.5 text-sm">{quote}</div>}
      </div>
    </div>
  )
}

function ReceiveDialog({ order, open, onClose, onDone, onError }: { order: PurchaseOrder; open: boolean; onClose: () => void; onDone: () => void; onError: (e: unknown) => void }) {
  const [amounts, setAmounts] = React.useState<Record<string, string>>({})
  const [date, setDate] = React.useState(today())
  React.useEffect(() => {
    if (open) {
      setAmounts(Object.fromEntries(order.lines.map((l) => [l.id, Number(l.pending) > 0 ? l.pending : ''])))
      setDate(today())
    }
  }, [open, order])
  const save = useMutation({
    mutationFn: () => receiveOrder(order.id, { occurred_date: date, lines: Object.entries(amounts).filter(([, v]) => Number(v) > 0).map(([line_id, quantity]) => ({ line_id, quantity })) }),
    onSuccess: onDone,
    onError,
  })
  const any = Object.values(amounts).some((v) => Number(v) > 0)
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Material came · {order.ref}</DialogTitle>
          <DialogDescription>From {order.vendor_name} at {order.site_name}. Stock goes up as soon as you save.</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (any) save.mutate() }}>
          {order.lines.map((line) => (
            <div key={line.id} className="flex items-center gap-2">
              <CategoryTile mainCategory={line.main_category} size="sm" />
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-semibold">{line.material}</span>
                <span className="block text-xs text-muted-foreground">{qty(line.pending, line.unit)} to come</span>
              </span>
              <div className="flex w-32 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                <Input aria-label={`${line.material} quantity`} inputMode="decimal" className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0" value={amounts[line.id] ?? ''} placeholder="0" onChange={(e) => setAmounts({ ...amounts, [line.id]: e.target.value.replace(/[^0-9.]/g, '') })} />
                <span className="pr-2.5 text-xs text-muted-foreground">{line.unit}</span>
              </div>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Label htmlFor="receive-date">Date</Label>
            <Input id="receive-date" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} className="w-[160px] dark:[color-scheme:dark]" />
          </div>
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={onClose}>Back</Button>
            <Button type="submit" disabled={!any || save.isPending} className="font-semibold">Save delivery</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ReasonDialog({ open, title, hint, placeholder, onClose, onSave }: { open: boolean; title: string; hint: string; placeholder: string; onClose: () => void; onSave: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  React.useEffect(() => { if (open) setReason('') }, [open])
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{hint}</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-2" onSubmit={async (e) => { e.preventDefault(); if (!reason.trim()) return; setBusy(true); await onSave(reason.trim()); setBusy(false) }}>
          <Label htmlFor="po-reason">Reason</Label>
          <Input id="po-reason" autoFocus value={reason} maxLength={300} placeholder={placeholder} onChange={(e) => setReason(e.target.value)} />
          <DialogFooter className="mt-3">
            <Button type="button" variant="outline" onClick={onClose}>Back</Button>
            <Button type="submit" variant="destructive" disabled={!reason.trim() || busy}>Confirm</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
