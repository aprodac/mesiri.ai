import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, CalendarDays, Camera, Check, ClipboardList, Clock, FileText, MessageCircle, PackageCheck, Pencil, Phone, RotateCcw, ShoppingCart, Truck, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/lib/AuthContext'
import { billFile } from '@/lib/bill-upload'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { cn } from '@/lib/utils'
import { URGENCY_LOOK, qty, swatch } from '@/lib/requests'
import { ORDER_LOOK, asMoreThanOrdered, cancelOrder, closeOrder, dueWords, fetchOrder, orderMessage, whatsappUrl, receiveOrder, reopenOrder, rupees, setDeliveryOrder, updateOrder, type PurchaseOrder } from '@/lib/orders'
import { NewOrderDialog } from './new-order-dialog'
import { CategoryTile, ProjectDot } from '@/components/requests/parts'
import { LinkedStrip } from '@/components/page/page-kit'
import { orderLinks } from '@/lib/links'
import { VendorLink } from '@/components/vendors/vendor-parts'

// PRC-06/08: one order, as the office and the site see it: the supplier, what was ordered and what came per line,
// the deliveries so far, the requests it covers, and the next step (receive, move the date, cancel, close short).

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
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

export function OrderDetail({ order: listed, inSheet }: { order: PurchaseOrder; inSheet?: boolean }) {
  // The list row first, then the order read on its own: its history and the deliveries here on no order.
  const full = useQuery({ queryKey: ['procurement', 'orders', 'one', listed.id], queryFn: () => fetchOrder(listed.id), staleTime: 15_000 })
  const order = full.data && full.data.id === listed.id ? full.data : listed
  const { me } = useAuth()
  const [dialog, setDialog] = React.useState<'receive' | 'cancel' | 'close' | 'edit' | null>(null)
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
  // PRC-23: a delivery recorded elsewhere put on this order (or taken off it). More than still to come is asked.
  const [extra, setExtra] = React.useState<{ receipt: string; line: string; message: string } | null>(null)
  const link = useMutation({
    mutationFn: ({ receipt, line, confirm }: { receipt: string; line: string | null; confirm?: boolean }) => setDeliveryOrder(receipt, { line_id: line, confirm_extra: confirm }),
    onSuccess: (_, v) => { setExtra(null); done(v.line ? `Counted on ${order.ref}` : `Taken off ${order.ref}`)() },
    onError: (err, v) => {
      const more = asMoreThanOrdered(err)
      if (more && v.line) return setExtra({ receipt: v.receipt, line: v.line, message: more.message })
      fail(err)
    },
  })
  const unlinked = order.unlinked_deliveries ?? []
  const reopen = useMutation({ mutationFn: () => reopenOrder(order.id), onSuccess: done(`${order.ref} is open again`), onError: fail })
  const open = order.status === 'open' || order.status === 'part'

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 bg-sky-50 px-5 pt-5 pb-4 dark:bg-sky-950/40">
        <div className={cn('flex items-center justify-between gap-2', inSheet && 'pr-8')}>
          <span className="text-xs font-semibold text-muted-foreground tabular-nums">{order.ref}{order.their_ref && <span className="ml-2 rounded bg-background px-1.5 py-0.5 font-medium">Their no. {order.their_ref}</span>}</span>
          <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold', ORDER_LOOK[order.status].chip)}>
            <span className={cn('size-1.5 rounded-full', ORDER_LOOK[order.status].dot)} />{ORDER_LOOK[order.status].label}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <VendorTile id={order.vendor_id} name={order.vendor_name} size="lg" />
          <div className="min-w-0">
            <h2 className="truncate text-xl leading-tight font-semibold"><VendorLink id={order.vendor_id} name={order.vendor_name} tab="account" /></h2>
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

      <LinkedStrip records={orderLinks(order)} className="border-b px-5 py-3" />

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
                {Number(line.rejected) > 0 && <span className="font-semibold text-destructive">{qty(line.rejected ?? '0', line.unit)} rejected</span>}
                {line.request && <span className="inline-flex items-center gap-1"><ClipboardList className="size-3" />{line.request.ref}</span>}
              </div>
            </div>
          )
        })}
      </div>

      {(order.grns ?? []).length > 0 && (
        <div className="flex flex-col gap-2 border-b px-5 py-4">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Goods received</h3>
          {(order.grns ?? []).map((g) => (
            <div key={g.id} className="flex items-start gap-3 rounded-lg border px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="font-semibold tabular-nums">{g.ref}</span>
                <span className="text-muted-foreground"> · {new Date(`${g.received_on}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}{g.challan_no ? ` · challan ${g.challan_no}` : ''}{g.received_by_name ? ` · ${g.received_by_name}` : ''}</span>
                {g.lines.map((l) => (
                  <span key={l.line_id} className="block text-xs">
                    {qty(l.accepted, l.unit)} {l.material} accepted{Number(l.rejected) > 0 && <span className="text-destructive"> · {qty(l.rejected, l.unit)} rejected ({l.rejected_reason})</span>}
                  </span>
                ))}
              </span>
              {g.photo_url && <a href={g.photo_url} target="_blank" rel="noreferrer" className="shrink-0 text-xs font-medium underline-offset-2 hover:underline">Challan photo</a>}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col px-5 py-4">
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">History</h3>
        <Step icon={ShoppingCart} title={`Ordered${order.created_by_name ? ` by ${order.created_by_name}` : ''}`} meta={when(order.created_at)} quote={order.notes} />
        {/* PRC-28: deliveries and changes, in the order they happened. */}
        {[
          ...order.deliveries.map((d) => ({ at: d.at, node: (
            <Step key={d.id} icon={Truck} title={`${qty(d.quantity, d.unit)} ${d.material} came`} meta={`${d.by_name ?? ''} · ${new Date(`${d.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`}
              action={open && order.may_receive ? { label: 'Not this order', onClick: () => link.mutate({ receipt: d.id, line: null }), busy: link.isPending } : undefined} />
          ) })),
          ...(order.history ?? []).map((h, i) => ({ at: h.at, node: (
            <Step key={`h${i}`} icon={HISTORY_ICON[h.kind] ?? Pencil} title={h.what} meta={`${h.by_name ?? ''} · ${when(h.at)}`} bad={h.kind === 'cancelled' || h.kind === 'closed'} />
          ) })),
        ].sort((a, b) => a.at.localeCompare(b.at)).map((x) => x.node)}
        {order.status === 'received' && <Step icon={PackageCheck} title="Everything came" />}
        {(order.status === 'closed' || order.status === 'cancelled') && !(order.history ?? []).some((h) => h.kind === order.status) && <Step icon={order.status === 'cancelled' ? Ban : Check} title={order.status === 'cancelled' ? 'Cancelled' : 'Closed short'} meta={`${order.status_by_name ?? ''}${order.status_at ? ` · ${when(order.status_at)}` : ''}`} quote={order.status_note} bad />}
        {open && <Step icon={Clock} title="Waiting for the rest" now />}
      </div>

      {open && order.may_receive && unlinked.length > 0 && (
        <div className="flex flex-col gap-2 border-t px-5 py-4">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Came here, on no order</h3>
          <p className="text-xs text-muted-foreground">Recorded in Materials or on WhatsApp since this order was placed. Count one on this order if it came from it.</p>
          {unlinked.map((d) => {
            const line = order.lines.find((l) => l.material_id === d.material_id)
            return (
              <div key={d.id} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">{qty(d.quantity, d.unit)} {d.material}</span>
                  <span className="block truncate text-xs text-muted-foreground">{[d.supplier, d.by_name, new Date(`${d.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })].filter(Boolean).join(' · ')}</span>
                </span>
                {line && <Button size="sm" variant="outline" disabled={link.isPending} onClick={() => link.mutate({ receipt: d.id, line: line.id })}>Count on {order.ref}</Button>}
              </div>
            )
          })}
          {extra && (
            <div className="flex flex-col gap-2 rounded-lg border border-orange-300 bg-orange-50 p-3 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
              <span>{extra.message}</span>
              <span className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setExtra(null)}>No</Button>
                <Button size="sm" className="bg-orange-600 text-white hover:bg-orange-700" disabled={link.isPending} onClick={() => link.mutate({ receipt: extra.receipt, line: extra.line, confirm: true })}>Yes, the extra came</Button>
              </span>
            </div>
          )}
        </div>
      )}

      {open && (
        <div className="flex flex-col gap-2 border-t px-5 py-4">
          {/* PRC-26: the order for the supplier, as a document or on WhatsApp; the person sends it. */}
          <div className="grid grid-cols-2 gap-2">
            <Button asChild variant="outline" className="h-10 gap-2"><Link to={`/procurement/orders/${order.id}/document`}><FileText className="size-4" /> PO document</Link></Button>
            <Button asChild variant="outline" className="h-10 gap-2 border-green-600/40 text-green-800 dark:text-green-300">
              <a href={whatsappUrl(order.vendor_phone, orderMessage(order, me?.org_name || me?.organization_name))} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send on WhatsApp</a>
            </Button>
          </div>
          {order.may_receive && (
            <Button className="h-11 gap-2 font-semibold" onClick={() => setDialog('receive')}><Truck className="size-4" /> Material came</Button>
          )}
          {order.may_edit || order.may_close ? (
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex h-10 items-center gap-2 rounded-md border px-2.5 text-sm">
                <CalendarDays className="size-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Expected</span>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} onBlur={() => date !== (order.expected_date ?? '') && move.mutate(date)} className="bg-transparent outline-none dark:[color-scheme:dark]" />
              </label>
              {order.may_edit && <Button variant="outline" className="h-10" onClick={() => setDialog('edit')}><Pencil className="size-4" /> Change</Button>}
              {order.may_cancel && <Button variant="outline" className="h-10 border-destructive/30 text-destructive" onClick={() => setDialog('cancel')}><X className="size-4" /> Cancel order</Button>}
              {order.may_close && <Button variant="outline" className="h-10" onClick={() => setDialog('close')}>Close short</Button>}
            </div>
          ) : null}
        </div>
      )}

      {order.may_reopen && (
        <div className="flex flex-col gap-1.5 border-t px-5 py-4">
          <Button variant="outline" className="h-10 gap-2" disabled={reopen.isPending} onClick={() => reopen.mutate()}><RotateCcw className="size-4" /> Open it again</Button>
          <p className="text-xs text-muted-foreground">The rest is coming after all, or it was {order.status === 'cancelled' ? 'cancelled' : 'closed'} by mistake. Its requests are ordered again.</p>
        </div>
      )}

      <NewOrderDialog open={dialog === 'edit'} onOpenChange={(o) => setDialog(o ? 'edit' : null)} scope={{ mode: 'portfolio' }} editing={order} />
      <ReceiveDialog order={order} open={dialog === 'receive'} onClose={() => setDialog(null)} onDone={done('Delivery recorded; stock is updated')} onError={fail} />
      <ReasonDialog
        open={dialog === 'cancel' || dialog === 'close'}
        title={dialog === 'cancel' ? `Cancel ${order.ref}` : `Close ${order.ref} short`}
        hint={dialog === 'cancel' ? 'Its requests go back to waiting; whoever asked is told on WhatsApp.' : 'What came stays; the rest is no longer expected. A request still short waits to be ordered again, and whoever asked is told.'}
        placeholder={dialog === 'cancel' ? 'Supplier has no stock' : 'Rest out of stock, ordering elsewhere'}
        onClose={() => setDialog(null)}
        onSave={(reason) => (dialog === 'cancel' ? cancelOrder(order.id, reason) : closeOrder(order.id, reason)).then(done(dialog === 'cancel' ? 'Order cancelled' : 'Order closed'), fail)}
      />
    </div>
  )
}

const HISTORY_ICON: Record<string, typeof Clock> = {
  date: CalendarDays, supplier: Phone, items: ShoppingCart, rates: ShoppingCart, their_ref: ClipboardList, notes: Pencil,
  cancelled: Ban, closed: Check, reopened: RotateCcw, delivery_on: Truck, delivery_off: Truck, grn: ClipboardList,
}

function Step({ icon: Icon, title, meta, quote, now, bad, action }: { icon: typeof Clock; title: string; meta?: string; quote?: string | null; now?: boolean; bad?: boolean; action?: { label: string; onClick: () => void; busy?: boolean } }) {
  return (
    <div className="flex gap-2.5">
      <span className={cn('mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full', now ? 'border-2 border-yellow-500 bg-yellow-50 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200' : bad ? 'bg-destructive/10 text-destructive' : 'bg-foreground text-background')}>
        <Icon className="size-3" strokeWidth={2.6} />
      </span>
      <div className="min-w-0 pb-3">
        <div className={cn('text-sm', now ? 'font-semibold' : 'font-medium')}>{title}</div>
        {meta && <div className="text-xs text-muted-foreground">{meta}{action && <> · <button type="button" disabled={action.busy} className="underline-offset-2 hover:underline" onClick={action.onClick}>{action.label}</button></>}</div>}
        {quote && <div className="mt-1 max-w-xs rounded-xl rounded-bl-sm bg-muted px-3 py-1.5 text-sm">{quote}</div>}
      </div>
    </div>
  )
}

/** WEB-79: "Material came" on its own, for Materials > Record delivery when the delivery is on an open order:
 * the same receiving (stock, the order, its GRN) as the order page, with the same toast. */
export function ReceiveOrderDialog({ order, lineId, open, onClose }: { order: PurchaseOrder | null; lineId?: string | null; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  if (!order) return null
  return (
    <ReceiveDialog
      order={order}
      lineId={lineId}
      open={open}
      onClose={onClose}
      onDone={() => {
        queryClient.invalidateQueries({ queryKey: ['procurement'] })
        queryClient.invalidateQueries({ queryKey: ['materials'] })
        toast.success(`Delivery recorded on ${order.ref}; stock is updated`)
        onClose()
      }}
      onError={(err) => toast.error('Not saved', errorText(err))}
    />
  )
}

function ReceiveDialog({ order, lineId, open, onClose, onDone, onError }: { order: PurchaseOrder; lineId?: string | null; open: boolean; onClose: () => void; onDone: () => void; onError: (e: unknown) => void }) {
  const { me } = useAuth()
  const [amounts, setAmounts] = React.useState<Record<string, string>>({})
  // PRC-29: the goods received note: some may be turned away at the gate (with why), the challan, who received it.
  const [rejected, setRejected] = React.useState<Record<string, string>>({})
  const [reasons, setReasons] = React.useState<Record<string, string>>({})
  const [checking, setChecking] = React.useState(false)
  const [challan, setChallan] = React.useState('')
  const [receivedBy, setReceivedBy] = React.useState('')
  const [photo, setPhoto] = React.useState<{ name: string; file: { content_type: string; data_base64: string } } | null>(null)
  const [photoError, setPhotoError] = React.useState('')
  const [date, setDate] = React.useState(today())
  // PRC-23: more than a line still has to come is asked before it is saved.
  const [extra, setExtra] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (open) {
      // WEB-79: from Materials > Record delivery for one item, only that line is filled in.
      setAmounts(Object.fromEntries(order.lines.map((l) => [l.id, Number(l.pending) > 0 && (!lineId || l.id === lineId) ? l.pending : ''])))
      setRejected({})
      setReasons({})
      setChecking(false)
      setChallan('')
      setReceivedBy(me?.name || me?.full_name || '')
      setPhoto(null)
      setPhotoError('')
      setDate(today())
      setExtra(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, order.id, lineId])
  const lines = order.lines
    .map((l) => ({ line_id: l.id, quantity: amounts[l.id] || '0', rejected: rejected[l.id] || '0', rejected_reason: reasons[l.id]?.trim() || null }))
    .filter((l) => Number(l.quantity) > 0 || Number(l.rejected) > 0)
  const missingReason = lines.some((l) => Number(l.rejected) > 0 && !l.rejected_reason)
  const save = useMutation({
    mutationFn: (confirm: boolean) => receiveOrder(order.id, {
      occurred_date: date, confirm_extra: confirm, lines,
      challan_no: challan.trim() || null, received_by_name: receivedBy.trim() || null, challan_photo: photo?.file ?? null,
    }),
    onSuccess: onDone,
    onError: (err) => {
      const more = asMoreThanOrdered(err)
      if (more) return setExtra(more.message)
      onError(err)
    },
  })
  const pickPhoto = async (file: File | undefined) => {
    setPhotoError('')
    if (!file) return
    try {
      setPhoto({ name: file.name, file: await billFile(file) })
    } catch (e) {
      setPhotoError(e instanceof Error ? e.message.replace(/bill/g, 'challan') : 'This photo could not be used.')
    }
  }
  const any = lines.length > 0
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Material came · {order.ref}</DialogTitle>
          <DialogDescription>From {order.vendor_name} at {order.site_name}. What you accept goes into stock as soon as you save.</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (any && !missingReason) save.mutate(false) }}>
          {order.lines.map((line) => (
            <div key={line.id} className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <CategoryTile mainCategory={line.main_category} size="sm" />
                <span className="min-w-0 flex-1 text-sm">
                  <span className="font-semibold">{line.material}</span>
                  <span className="block text-xs text-muted-foreground">{qty(line.pending, line.unit)} to come</span>
                </span>
                <div className="flex w-32 items-center rounded-md border focus-within:ring-2 focus-within:ring-ring">
                  <Input aria-label={`${line.material} accepted`} inputMode="decimal" className="border-0 text-right font-semibold tabular-nums shadow-none focus-visible:ring-0" value={amounts[line.id] ?? ''} placeholder="0" onChange={(e) => { setExtra(null); setAmounts({ ...amounts, [line.id]: e.target.value.replace(/[^0-9.]/g, '') }) }} />
                  <span className="pr-2.5 text-xs text-muted-foreground">{line.unit}</span>
                </div>
              </div>
              {checking && (
                <div className="ml-8 flex flex-wrap items-center gap-2">
                  <div className="flex w-28 items-center rounded-md border border-destructive/30 focus-within:ring-2 focus-within:ring-ring">
                    <Input aria-label={`${line.material} rejected`} inputMode="decimal" className="h-8 border-0 text-right tabular-nums shadow-none focus-visible:ring-0" value={rejected[line.id] ?? ''} placeholder="0" onChange={(e) => setRejected({ ...rejected, [line.id]: e.target.value.replace(/[^0-9.]/g, '') })} />
                    <span className="pr-2 text-xs text-destructive">rejected</span>
                  </div>
                  {Number(rejected[line.id]) > 0 && (
                    <Input aria-label={`Why ${line.material} was rejected`} className="h-8 min-w-[160px] flex-1" placeholder="Why: torn bags, wrong size…" value={reasons[line.id] ?? ''} onChange={(e) => setReasons({ ...reasons, [line.id]: e.target.value })} />
                  )}
                </div>
              )}
            </div>
          ))}
          {!checking && (
            <button type="button" className="w-fit text-xs font-medium text-muted-foreground underline-offset-2 hover:underline" onClick={() => setChecking(true)}>Some of it rejected at the gate?</button>
          )}
          {checking && <p className="text-xs text-muted-foreground">Rejected material does not go into stock; it stays to come on the order (a replacement is owed).</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="receive-challan">Challan no. <span className="font-normal text-muted-foreground">(optional)</span></Label>
              <Input id="receive-challan" value={challan} maxLength={60} placeholder="DC-5531" onChange={(e) => setChallan(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="receive-by">Received by</Label>
              <Input id="receive-by" value={receivedBy} maxLength={120} placeholder="Name" onChange={(e) => setReceivedBy(e.target.value)} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm hover:bg-muted/50">
              <Camera className="size-4" /> {photo ? 'Change challan photo' : 'Challan photo'}
              <input type="file" accept="image/*,application/pdf" capture="environment" className="sr-only" onChange={(e) => pickPhoto(e.target.files?.[0])} />
            </label>
            {photo && <span className="truncate text-xs text-success">✓ {photo.name}</span>}
            {photoError && <span className="text-xs text-destructive">{photoError}</span>}
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="receive-date">Date</Label>
            <Input id="receive-date" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} className="w-[160px] dark:[color-scheme:dark]" />
          </div>
          {missingReason && <p className="text-xs text-destructive">Say why it was rejected.</p>}
          {extra && (
            <div className="rounded-lg border border-orange-300 bg-orange-50 px-3 py-2 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100" role="alert">{extra}</div>
          )}
          <DialogFooter className="mt-2">
            <Button type="button" variant="outline" onClick={onClose}>Back</Button>
            {extra
              ? <Button type="button" disabled={save.isPending} className="bg-orange-600 font-semibold text-white hover:bg-orange-700" onClick={() => save.mutate(true)}>Yes, the extra came</Button>
              : <Button type="submit" disabled={!any || missingReason || save.isPending} className="font-semibold">Save delivery</Button>}
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
