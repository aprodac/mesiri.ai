import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BarChart3, Check, Clock, Copy, Home, IndianRupee, MessageCircle, PackageCheck, Pencil, RotateCcw, ShoppingCart, Truck, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/toast-notification'
import { cn } from '@/lib/utils'
import {
  STATUS_LOOK,
  URGENCY_LOOK,
  boughtOutside,
  cancelRequest,
  decideRequest,
  reopenRequest,
  neededWords,
  qty,
  type Decision,
  type MaterialRequest,
  type RequestLine,
  type RequestOrder,
} from '@/lib/requests'
import { ORDER_LOOK } from '@/lib/orders'
import { Avatar, CategoryTile, CoverBar, ProjectDot, StatusChip } from './parts'
import { NewOrderDialog, type OrderPrefill } from '@/components/orders/new-order-dialog'
import { NewRequestDialog } from './new-request-dialog'

// PRC-22: one request, as the office acts on it: what is asked, what is here / ordered / still to buy, other sites
// that hold some, the last rate (money roles only), what happened so far, and the one next step.

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : 'That did not save. Try again.'
}

function when(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function RequestDetail({ request, className, inSheet }: { request: MaterialRequest; className?: string; inSheet?: boolean }) {
  const first = request.lines[0]
  const main = request.lines.length === 1 ? first?.main_category ?? null : null
  const [decision, setDecision] = React.useState<Act | null>(null)
  // PRC-06: a purchase order made from this request, filled in with what is still to buy at its site.
  const [ordering, setOrdering] = React.useState(false)
  // PRC-31: change it while it waits; bring it back once said no to or taken back.
  const [editing, setEditing] = React.useState(false)
  const prefill = React.useMemo<OrderPrefill>(() => ({
    project_id: request.project_id,
    site_id: request.site_id,
    site_name: request.site_name,
    request_ref: request.ref,
    lines: request.lines.map((l) => ({ material_id: l.material_id, quantity: Number(l.to_buy) > 0 ? l.to_buy : l.quantity, request_line_id: l.id })),
  }), [request])
  const queryClient = useQueryClient()
  const toast = useToast()

  const act = useMutation({
    mutationFn: ({ action, note }: { action: Act | 'cancel' | 'reopen'; note?: string }) =>
      action === 'cancel' ? cancelRequest(request.id) : action === 'reopen' ? reopenRequest(request.id)
        : action === 'outside' ? boughtOutside(request.id, note) : decideRequest(request.id, action, note),
    onSuccess: (after) => {
      queryClient.invalidateQueries({ queryKey: ['procurement', 'requests'] })
      setDecision(null)
      toast.success(`${after.ref}: ${STATUS_LOOK[after.status].label}`, after.requested_by_name && after.status !== 'cancelled' ? `${after.requested_by_name} is told on WhatsApp.` : undefined)
    },
    onError: (err) => toast.error('Not saved', errorText(err)),
  })

  const single = request.lines.length === 1 ? first : null
  const buyWords = single && Number(single.to_buy) > 0 ? ` · ${qty(single.to_buy, single.unit)}` : ''
  const spare = request.lines.flatMap((l) => l.elsewhere.map((e) => ({ ...e, line: l })))

  return (
    <div className={cn('flex flex-col', className)}>
      <div className={cn('flex flex-col gap-3 px-5 pt-5 pb-4', main ? categoryBand(main) : 'bg-muted/50')}>
        <div className={cn('flex items-center justify-between gap-2', inSheet && 'pr-8')}>
          <span className="inline-flex items-center gap-2 text-xs font-semibold">
            <CategoryTile mainCategory={main} size="sm" />
            {main ?? (request.lines.length > 1 ? `${request.lines.length} items` : 'No category')}
          </span>
          <span className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground tabular-nums">{request.ref}</span>
            <StatusChip status={request.status} />
          </span>
        </div>
        {single ? (
          <div>
            <h2 className="text-xl leading-tight font-semibold">{single.material}</h2>
            <div className="text-2xl font-semibold tabular-nums">{qty(single.quantity, single.unit)}</div>
            {single.said && <div className="text-xs text-muted-foreground">asked as {single.said}</div>}
          </div>
        ) : (
          <h2 className="text-xl leading-tight font-semibold">{request.lines.length} items</h2>
        )}
        <div className="flex flex-wrap gap-1.5 text-xs">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-background px-2.5 py-1"><ProjectDot id={request.project_id} />{request.project_name} › {request.site_name}</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-background py-0.5 pr-2.5 pl-1"><Avatar id={request.requested_by} name={request.requested_by_name} />{request.requested_by_name ?? 'Someone'}</span>
          {request.purpose && <span className="rounded-full bg-background px-2.5 py-1">For: {request.purpose}</span>}
        </div>
        <div className={cn('flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold', URGENCY_LOOK[request.urgency].chip)}>
          <Clock className="size-4" strokeWidth={2.4} />
          {request.needed_by && request.urgency !== 'closed' ? `Needed: ${neededWords(request)}` : neededWords(request)}
        </div>
      </div>

      {request.duplicates.length > 0 && request.status === 'waiting' && (
        <div className="mx-5 mt-4 flex items-start gap-2 rounded-lg bg-orange-100 px-3 py-2.5 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
          <Copy className="mt-0.5 size-4 shrink-0" />
          <span>
            <strong>Possible duplicate:</strong>{' '}
            {request.duplicates.map((d) => `${d.ref} (${d.requested_by_name ?? 'someone'}, ${STATUS_LOOK[d.status].label.toLowerCase()})`).join(', ')}
          </span>
        </div>
      )}

      <div className={cn('flex flex-col gap-4 border-b px-5 py-4', !['waiting', 'ordered', 'sent'].includes(request.status) && 'hidden')}>
        {request.lines.map((line) => <LineCover key={line.id} line={line} showName={!single} open={request.status === 'waiting'} />)}
        {request.status === 'waiting' && spare.length > 0 && (
          <div className="flex items-start gap-2 rounded-lg bg-fuchsia-100 px-3 py-2.5 text-sm font-semibold text-fuchsia-900 dark:bg-fuchsia-950 dark:text-fuchsia-100">
            <ArrowRight className="mt-0.5 size-4 shrink-0" strokeWidth={2.6} />
            <span>{spare.map((s) => `${qty(s.quantity, s.line.unit)}${single ? '' : ` ${s.line.material}`} at ${s.site_name}`).join(' · ')}</span>
          </div>
        )}
      </div>

      {request.orders.length > 0 && <OrdersBlock orders={request.orders} />}

      {request.lines.some((l) => l.last_rate) && (
        <div className="grid grid-cols-1 gap-2 border-b px-5 py-4 sm:grid-cols-2">
          {request.lines.filter((l) => l.last_rate).map((l) => (
            <div key={l.id} className="rounded-lg border px-3 py-2">
              <div className="flex items-center gap-1 text-[11px] font-semibold text-muted-foreground"><IndianRupee className="size-3" />Last rate{single ? '' : ` · ${l.material}`}</div>
              <div className="font-semibold tabular-nums">₹{Number(l.last_rate!.unit_cost).toLocaleString('en-IN')} / {l.unit}</div>
              <div className="truncate text-xs text-muted-foreground">{[l.last_rate!.supplier, l.last_rate!.occurred_date && new Date(`${l.last_rate!.occurred_date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })].filter(Boolean).join(' · ')}</div>
            </div>
          ))}
        </div>
      )}

      <History request={request} />

      {(request.may_edit || request.may_reopen) && (
        <div className="flex flex-wrap gap-2 px-5 pb-1">
          {request.may_edit && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setEditing(true)}><Pencil className="size-3.5" /> Change request</Button>
          )}
          {request.may_reopen && (
            <Button variant="outline" size="sm" className="gap-1.5" disabled={act.isPending} onClick={() => act.mutate({ action: 'reopen' })}><RotateCcw className="size-3.5" /> Bring it back</Button>
          )}
        </div>
      )}

      {(request.may_act || request.may_cancel) && !['done', 'rejected', 'cancelled'].includes(request.status) && (
        <div className="mt-auto flex flex-wrap gap-2 border-t px-5 py-4">
          {request.may_act && request.status === 'waiting' && (
            <>
              <Button className="h-11 basis-full gap-2 font-semibold" onClick={() => setOrdering(true)}>
                <ShoppingCart className="size-4" /> Create order{buyWords}
              </Button>
              {request.may_decide && (<>
              <Button variant="outline" className="h-11 flex-1 gap-2 border-fuchsia-300 bg-fuchsia-50 font-semibold text-fuchsia-900 hover:bg-fuchsia-100 dark:bg-fuchsia-950 dark:text-fuchsia-100" onClick={() => setDecision('sent')}>
                <ArrowRight className="size-4" /> Sent from a site
              </Button>
              <Button variant="outline" size="icon" className="size-11 border-destructive/30 text-destructive" title="Not ordering it" aria-label="Not ordering it" onClick={() => setDecision('rejected')}>
                <X className="size-4" strokeWidth={2.6} />
              </Button>
              <button type="button" className="basis-full text-left text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => setDecision('outside')}>
                Ordered outside Mesiri? Mark it ordered
              </button>
              </>)}
            </>
          )}
          {request.may_act && request.follows_order && (
            // PRC-23: an open order covers it; it is received when the delivery is recorded against the order.
            <p className="w-full text-sm text-muted-foreground">
              Moves with its order: it is received when the delivery is recorded against{' '}
              {request.orders.filter((o) => o.status === 'open' || o.status === 'part').map((o) => o.ref).join(', ') || 'the order'}.{' '}
              <button type="button" className="font-medium text-foreground underline-offset-2 hover:underline" onClick={() => setDecision('outside')}>Got the rest outside Mesiri?</button>
            </p>
          )}
          {request.may_decide && (request.status === 'ordered' || request.status === 'sent') && (
            <div className="flex w-full flex-col gap-1.5">
              <Button className="h-11 gap-2 font-semibold" disabled={act.isPending} onClick={() => act.mutate({ action: 'done' })}>
                <PackageCheck className="size-4" /> Mark received
              </Button>
              <p className="text-xs text-muted-foreground">
                This closes the request. To add it to stock, <Link to="/materials?view=movements" className="underline">record the delivery</Link>.
              </p>
            </div>
          )}
          {request.may_cancel && !request.may_act && (
            <Button variant="outline" className="h-11 flex-1" disabled={act.isPending} onClick={() => act.mutate({ action: 'cancel' })}>
              Cancel my request
            </Button>
          )}
        </div>
      )}

      <NewOrderDialog open={ordering} onOpenChange={setOrdering} scope={{ mode: 'portfolio' }} prefill={prefill} />
      <NewRequestDialog open={editing} onOpenChange={setEditing} scope={{ mode: 'portfolio' }} editing={request} />
      <DecisionDialog
        request={request}
        action={decision}
        pending={act.isPending}
        onClose={() => setDecision(null)}
        onSave={(note) => decision && act.mutate({ action: decision, note })}
      />
    </div>
  )
}

function OrdersBlock({ orders }: { orders: RequestOrder[] }) {
  // PRC-23: the purchase orders behind the request, each with what came of what was ordered.
  return (
    <div className="flex flex-col gap-2 border-b px-5 py-4">
      <div className="text-xs font-semibold text-muted-foreground">Orders</div>
      {orders.map((o) => (
        <Link key={o.id} to={`/procurement/orders?id=${o.id}`} className={cn('flex items-center gap-3 rounded-lg border px-3 py-2 text-sm hover:bg-muted/40', o.status === 'cancelled' && 'opacity-60')}>
          <ShoppingCart className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1">
            <span className="font-semibold tabular-nums">{o.ref}</span> · {o.vendor_name}
            <span className="block truncate text-xs text-muted-foreground">
              {o.lines.map((l) => `${qty(l.received, l.unit)} of ${qty(l.quantity, l.unit)} came${o.lines.length > 1 ? ` (${l.material})` : ''}`).join(' · ')}
            </span>
          </span>
          <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold', ORDER_LOOK[o.status].chip)}>{ORDER_LOOK[o.status].label}</span>
        </Link>
      ))}
    </div>
  )
}

function categoryBand(main: string): string {
  // A light wash of the category's colour behind the head, so the panel says what kind of thing it is at a glance.
  if (/electric/i.test(main)) return 'bg-amber-50 dark:bg-amber-950/40'
  if (/plumb|sanit|water/i.test(main)) return 'bg-blue-50 dark:bg-blue-950/40'
  if (/fire/i.test(main)) return 'bg-red-50 dark:bg-red-950/40'
  if (/finish|paint/i.test(main)) return 'bg-violet-50 dark:bg-violet-950/40'
  if (/gas/i.test(main)) return 'bg-teal-50 dark:bg-teal-950/40'
  if (/lift/i.test(main)) return 'bg-cyan-50 dark:bg-cyan-950/40'
  return 'bg-slate-100 dark:bg-slate-900'
}

function LineCover({ line, showName, open }: { line: RequestLine; showName: boolean; open: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      {showName && (
        <div className="flex items-center gap-2 text-sm font-semibold">
          <CategoryTile mainCategory={line.main_category} size="sm" />
          {line.material} <span className="tabular-nums text-muted-foreground">{qty(line.quantity, line.unit)}</span>
        </div>
      )}
      <CoverBar line={line} className="h-3.5" />
      <div className="grid grid-cols-3 gap-2 text-xs">
        <Stat icon={Home} label="At site" value={qty(line.at_site, line.unit)} tone="bg-success-soft text-success" />
        <Stat icon={Truck} label="Coming" value={qty(line.on_order, line.unit)} tone="bg-info-soft text-info" />
        <Stat icon={ShoppingCart} label="To buy" value={qty(line.to_buy, line.unit)} tone={open && Number(line.to_buy) > 0 ? 'bg-yellow-400 text-stone-950' : 'bg-muted text-muted-foreground'} />
      </div>
    </div>
  )
}

function Stat({ icon: Icon, label, value, tone }: { icon: typeof Home; label: string; value: string; tone: string }) {
  return (
    <div className={cn('rounded-lg px-2.5 py-2', tone)}>
      <div className="flex items-center gap-1 text-[11px] font-semibold"><Icon className="size-3" />{label}</div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
    </div>
  )
}

type Step = { icon: typeof Check; title: string; meta?: string; quote?: string; tone: 'done' | 'now' | 'bad' }

function History({ request }: { request: MaterialRequest }) {
  const steps: Step[] = [
    { icon: request.source === 'whatsapp' ? MessageCircle : Check, title: request.source === 'whatsapp' ? 'Asked on WhatsApp' : 'Asked', meta: `${request.requested_by_name ?? ''} · ${when(request.created_at)}`, tone: 'done' },
  ]
  if (request.raised_over_duplicate) steps.push({ icon: Copy, title: 'Raised after the duplicate warning', tone: 'done' })
  if (request.decided_at && request.status !== 'cancelled') {
    const label = { ordered: 'Ordered', sent: 'Sent from a site', rejected: 'Not ordered', done: 'Ordered', waiting: '', cancelled: '' }[request.status] || 'Decided'
    steps.push({ icon: request.status === 'rejected' ? X : request.status === 'sent' ? ArrowRight : ShoppingCart, title: label, meta: `${request.decided_by_name ?? ''} · ${when(request.decided_at)}`, quote: request.decision_note ?? undefined, tone: request.status === 'rejected' ? 'bad' : 'done' })
  }
  if (request.status === 'done' && request.done_at) steps.push({ icon: PackageCheck, title: 'Received', meta: when(request.done_at), tone: 'done' })
  if (request.status === 'cancelled') steps.push({ icon: X, title: 'Cancelled', tone: 'bad' })
  if (request.status === 'waiting') steps.push({ icon: Clock, title: 'Waiting for the office', tone: 'now' })
  if (request.status === 'ordered' || request.status === 'sent') steps.push({ icon: Truck, title: 'On its way', tone: 'now' })

  return (
    <div className="flex flex-col px-5 py-4">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase"><BarChart3 className="size-3.5" />History</h3>
      {steps.map((s, i) => (
        <div key={i} className="flex gap-2.5">
          <div className="flex flex-col items-center">
            <span className={cn('inline-flex size-6 items-center justify-center rounded-full', {
              done: 'bg-foreground text-background',
              now: 'border-2 border-yellow-500 bg-yellow-50 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200',
              bad: 'bg-destructive/10 text-destructive',
            }[s.tone])}>
              <s.icon className="size-3" strokeWidth={2.6} />
            </span>
            {i < steps.length - 1 && <span className="min-h-3 w-0.5 flex-1 bg-border" />}
          </div>
          <div className="min-w-0 pb-3">
            <div className={cn('text-sm', s.tone === 'now' ? 'font-semibold' : 'font-medium')}>{s.title}</div>
            {s.meta && <div className="text-xs text-muted-foreground">{s.meta}</div>}
            {s.quote && <div className="mt-1 max-w-xs rounded-xl rounded-bl-sm bg-muted px-3 py-1.5 text-sm">{s.quote}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}

/** PRC-30: an office decision, or "got it outside Mesiri" (one step; its open orders stop). */
type Act = Decision | 'outside'

const DECISION_WORDS: Record<Act, { title: string; label: string; placeholder: string; required: boolean; button: string }> = {
  outside: { title: 'Got it outside Mesiri', label: 'From whom, how (optional)', placeholder: 'By phone from KK Traders', required: false, button: 'Mark ordered outside' },
  ordered: { title: 'Mark ordered', label: 'Supplier or note (optional)', placeholder: 'Malabar Hardware, ₹400 a bag', required: false, button: 'Mark ordered' },
  sent: { title: 'Sent from another site', label: 'From which site (optional)', placeholder: 'Yard', required: false, button: 'Mark sent' },
  rejected: { title: 'Not ordering it', label: 'Reason', placeholder: '52 bags already at the site', required: true, button: 'Not ordering' },
  done: { title: 'Mark received', label: 'Note (optional)', placeholder: '', required: false, button: 'Mark received' },
}

function DecisionDialog({ request, action, pending, onClose, onSave }: { request: MaterialRequest; action: Act | null; pending: boolean; onClose: () => void; onSave: (note: string) => void }) {
  const [note, setNote] = React.useState('')
  React.useEffect(() => {
    if (action === 'sent') setNote(request.lines[0]?.elsewhere[0]?.site_name ?? '')
    else setNote('')
  }, [action, request])
  if (!action) return null
  const words = DECISION_WORDS[action]
  const blocked = words.required && !note.trim()
  return (
    <Dialog open={!!action} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{words.title}</DialogTitle>
          <DialogDescription>
            {request.ref} · {request.lines.map((l) => `${qty(l.quantity, l.unit)} ${l.material}`).join(', ')}.{action === 'outside' && request.follows_order ? ' Its open order stops (closed short if part came).' : ''} {request.requested_by_name ?? 'The person who asked'} is told on WhatsApp.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!blocked) onSave(note.trim())
          }}
        >
          <Label htmlFor="decision-note">{words.label}</Label>
          <Input id="decision-note" autoFocus value={note} placeholder={words.placeholder} maxLength={300} onChange={(e) => setNote(e.target.value)} />
          <DialogFooter className="mt-3">
            <Button type="button" variant="outline" onClick={onClose}>Back</Button>
            <Button type="submit" disabled={blocked || pending} variant={action === 'rejected' ? 'destructive' : 'default'}>{words.button}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
