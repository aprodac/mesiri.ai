import * as React from 'react'
import { ScoreChip } from '@/components/vendors/supplier-score'
import { useSupplierScores } from '@/lib/supplier-performance'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, CheckCircle2, Clock, Crown, FileText, MessageCircle, MoreHorizontal, PackagePlus, Pencil, Plus, Scale, Send, ShoppingCart, Store, TrendingDown, TrendingUp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { useIsMobile } from '@/hooks/use-mobile'
import { cn } from '@/lib/utils'
import { rupees, whatsappUrl } from '@/lib/orders'
import { rate } from '@/lib/rates'
import { asDuplicateConflict } from '@/lib/requests'
import {
  RFQ_LOOK, SUPPLIER_LOOK, addRfqSupplier, asReasonNeeded, awardRfq, closeRfq, declineRfq, dueWords, fetchRfq, markRfqSent, rfqMessage, thanksMessage,
  type AwardPayload, type QuoteCell, type Rfq, type RfqLine, type RfqSupplier,
} from '@/lib/rfqs'
import { CategoryTile, ProjectDot } from '@/components/requests/parts'
import { VendorTile } from '@/components/orders/order-detail'
import { QuoteDialog } from '@/components/quotations/quote-dialog'

// PRC-41..43: one RFQ. Who was asked and what each answered (send the RFQ on WhatsApp, record or revise a quote,
// mark a refusal); the comparison sheet: items down, suppliers across, every rate as it costs the company, the
// cheapest per item in green and the dearest in red, the last price paid under each item; the two ways to buy with
// what each costs; and ordering: all from one supplier, the cheapest per item, or the cells picked.

const day = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

export function RfqDetail({ rfq: listed, inSheet }: { rfq: Rfq; inSheet?: boolean }) {
  const { me } = useAuth()
  const company = me?.org_name || me?.organization_name
  const { data } = useQuery({ queryKey: ['procurement', 'rfq', listed.id], queryFn: () => fetchRfq(listed.id), initialData: listed, staleTime: 5_000 })
  const r = data ?? listed
  const scores = useSupplierScores()  // PRC-50: each supplier's score beside its name
  const queryClient = useQueryClient()
  const toast = useToast()
  const [quoting, setQuoting] = React.useState<RfqSupplier | null>(null)
  const [picks, setPicks] = React.useState<Record<string, string>>({})  // line id -> rfq_vendor_id
  const [awarding, setAwarding] = React.useState<AwardPayload | null>(null)
  const [ending, setEnding] = React.useState<'close' | 'cancel' | null>(null)
  React.useEffect(() => setPicks({}), [r.id])

  const done = (next: Rfq) => {
    queryClient.setQueryData(['procurement', 'rfq', next.id], next)
    queryClient.invalidateQueries({ queryKey: ['procurement'] })
  }
  const sent = useMutation({ mutationFn: (rv: string) => markRfqSent(r.id, rv), onSuccess: done })
  const look = RFQ_LOOK[r.status]
  const seesMoney = r.lines.some((l) => l.quotes.some((q) => q.cost !== undefined)) || r.lowest_total !== null || r.suppliers.some((s) => s.total !== null)
  const quoted = r.suppliers.filter((s) => s.status === 'quoted')
  const due = dueWords(r)
  const live = r.status === 'open' || r.status === 'ready'

  return (
    <div className="flex flex-col">
      <header className={cn('flex flex-col gap-2 px-4 pt-4 pb-3 sm:px-5', inSheet && 'pt-5 pr-12')}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold text-muted-foreground tabular-nums">{r.ref}{r.request ? <> · for <Link className="hover:underline" to={`/materials/requests?id=${r.request.id}`}>{r.request.ref}</Link></> : null}</span>
          <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </div>
        <h2 className="text-xl font-semibold leading-tight">{r.lines.length === 1 ? `${r.lines[0].material} · ${Number(r.lines[0].quantity).toLocaleString('en-IN')} ${r.lines[0].unit}` : `${r.lines.length} items`}</h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><ProjectDot id={r.project_id} />{r.project_name} › {r.site_name}</span>
          {r.needed_by && <span>Needed by {day(r.needed_by)}</span>}
          {due && <span className={cn('inline-flex items-center gap-1', r.due_days !== null && r.due_days < 0 && 'font-semibold text-destructive')}><Clock className="size-3.5" />{due}</span>}
        </div>
        {r.status === 'awarded' && r.orders.length > 0 && (
          <div className="mt-1 flex flex-wrap items-center gap-2 rounded-xl bg-teal-50 p-2.5 text-sm text-teal-950 dark:bg-teal-950 dark:text-teal-100">
            <CheckCircle2 className="size-4" /> Ordered:
            {r.orders.map((o) => <Link key={o.id} to={`/procurement/orders?id=${o.id}`} className="rounded-md bg-background/70 px-2 py-0.5 font-semibold tabular-nums hover:underline">{o.ref}</Link>)}
          </div>
        )}
        {(r.status === 'closed' || r.status === 'cancelled') && r.status_note && <p className="text-sm text-muted-foreground">{look.label}: {r.status_note}</p>}
      </header>

      <Section title="Suppliers" count={r.suppliers.length} hint={`${r.counts.quoted} quoted · ${r.counts.invited} waiting${r.counts.declined ? ` · ${r.counts.declined} declined` : ''}`}>
        <ul className="flex flex-col gap-2">
          {r.suppliers.map((s) => (
            <li key={s.rfq_vendor_id} className={cn('flex flex-col gap-2 rounded-xl border p-3', s.best_total && 'border-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/30')}>
              <div className="flex items-center gap-2.5">
                <VendorTile id={s.vendor_id} name={s.name} />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-center gap-2"><span className="truncate font-semibold">{s.name}</span><ScoreChip p={scores.get(s.vendor_id)} />{s.best_total && <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-600 px-1.5 py-0.5 text-[10px] font-bold whitespace-nowrap text-white" title="Cheapest of the suppliers who quoted every item"><Crown className="size-3" /><span className="hidden sm:inline">Best total</span></span>}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {s.status === 'quoted' ? [s.total ? `${rupees(s.total)} for ${s.lines_quoted} of ${r.lines.length}` : `${s.lines_quoted} of ${r.lines.length} items`, s.delivery_days != null ? `${s.delivery_days}d delivery` : null, s.payment_days != null ? `${s.payment_days}d credit` : null, s.valid_until ? `valid to ${day(s.valid_until)}` : null].filter(Boolean).join(' · ')
                      : s.status === 'declined' ? s.decline_reason || 'Will not quote'
                        : s.sent_at ? `Sent ${new Date(s.sent_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} · waiting` : 'Not sent yet'}
                  </span>
                </span>
                <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', SUPPLIER_LOOK[s.status].chip)}>{SUPPLIER_LOOK[s.status].label}</span>
              </div>
              {r.may_record && (
                <div className="flex flex-wrap items-center gap-2 pl-[52px]">
                  {s.status !== 'quoted' && (
                    <Button asChild size="sm" variant={s.sent_at ? 'ghost' : 'outline'} className="h-8 gap-1.5">
                      <a href={whatsappUrl(s.phone, rfqMessage(r, company))} target="_blank" rel="noreferrer" onClick={() => !s.sent_at && sent.mutate(s.rfq_vendor_id)}>
                        {s.sent_at ? <Check className="size-3.5" /> : <Send className="size-3.5" />}{s.sent_at ? 'Send again' : 'Send on WhatsApp'}
                      </a>
                    </Button>
                  )}
                  <Button size="sm" className="h-8 gap-1.5 font-semibold" variant={s.status === 'quoted' ? 'outline' : 'default'} onClick={() => setQuoting(s)}>
                    {s.status === 'quoted' ? <><Pencil className="size-3.5" />Revise quote</> : <><Plus className="size-3.5" />Record quote</>}
                  </Button>
                  {s.status !== 'declined' && <DeclineMenu rfq={r} supplier={s} onDone={done} />}
                </div>
              )}
              {r.status === 'awarded' && s.status === 'quoted' && !r.lines.some((l) => l.quotes.some((q) => q.rfq_vendor_id === s.rfq_vendor_id && q.quote_line_id === l.awarded_quote_line_id)) && (
                <div className="pl-[52px]">
                  <Button asChild size="sm" variant="ghost" className="h-8 gap-1.5 text-muted-foreground"><a href={whatsappUrl(s.phone, thanksMessage(r, s.name))} target="_blank" rel="noreferrer"><MessageCircle className="size-3.5" />Thank them</a></Button>
                </div>
              )}
            </li>
          ))}
        </ul>
        {r.may_record && <AddSupplier rfq={r} onDone={done} />}
      </Section>

      {quoted.length > 0 && seesMoney && (
        <Section title="Compare" icon={Scale} hint="As each costs you: before GST from a supplier with a GSTIN (you claim it back), with GST from one without.">
          <CompareSheet rfq={r} picks={picks} onPick={r.may_award ? (line, rv) => setPicks((p) => ({ ...p, [line]: p[line] === rv ? '' : rv })) : undefined} />
          <WaysToBuy rfq={r} picks={picks} onAward={r.may_award ? setAwarding : undefined} />
        </Section>
      )}
      {quoted.length > 0 && !seesMoney && (
        <Section title="Compare"><p className="text-sm text-muted-foreground">{quoted.length} supplier{quoted.length === 1 ? ' has' : 's have'} quoted. Rates are shown to the people who see spending.</p></Section>
      )}
      {quoted.length === 0 && live && (
        <Section title="Compare">
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
            <Scale className="size-7 opacity-40" />
            Send the RFQ to each supplier, then record their rates as they reply (or forward the quote on WhatsApp to Mesiri). The comparison fills in here.
          </div>
        </Section>
      )}

      {(r.terms || r.notes) && (
        <Section title="Terms asked">
          <p className="text-sm">{r.terms}{r.notes ? <span className="block text-muted-foreground">{r.notes}</span> : null}</p>
        </Section>
      )}

      {r.may_cancel && (
        <footer className="flex flex-wrap gap-2 border-t px-4 py-3 sm:px-5">
          <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => setEnding('close')}><FileText className="size-3.5" />Close without ordering</Button>
          <Button variant="ghost" size="sm" className="gap-1.5 text-destructive hover:text-destructive" onClick={() => setEnding('cancel')}><Ban className="size-3.5" />Cancel RFQ</Button>
        </footer>
      )}

      <QuoteDialog rfq={r} supplier={quoting} open={!!quoting} onOpenChange={(o) => !o && setQuoting(null)} />
      <AwardDialog rfq={r} payload={awarding} onClose={() => setAwarding(null)} onDone={(next) => { done(next); setPicks({}); toast.success(`Ordered from ${next.ref}`, next.orders.map((o) => o.ref).join(', ')) }} />
      <EndDialog rfq={r} kind={ending} onClose={() => setEnding(null)} onDone={done} />
    </div>
  )
}

function Section({ title, count, hint, icon: Icon, children }: { title: string; count?: number; hint?: string; icon?: typeof Store; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 border-t px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h3 className="inline-flex items-center gap-1.5 text-xs font-bold tracking-wide text-muted-foreground uppercase">{Icon && <Icon className="size-3.5" />}{title}</h3>
        {count !== undefined && <span className="rounded-full bg-muted px-1.5 text-[11px] font-semibold tabular-nums">{count}</span>}
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

function AddSupplier({ rfq, onDone }: { rfq: Rfq; onDone: (r: Rfq) => void }) {
  const [name, setName] = React.useState('')
  const add = useMutation({ mutationFn: () => addRfqSupplier(rfq.id, name.trim()), onSuccess: (r) => { onDone(r); setName('') } })
  return (
    <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate() }}>
      <div className="flex flex-1 items-center gap-2 rounded-md border px-2.5 focus-within:ring-2 focus-within:ring-ring">
        <Store className="size-4 text-muted-foreground" />
        <input aria-label="Ask another supplier" className="h-9 flex-1 bg-transparent text-sm outline-none" placeholder="Ask another supplier" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <Button type="submit" size="sm" variant="outline" disabled={!name.trim() || add.isPending}>Add</Button>
    </form>
  )
}

function DeclineMenu({ rfq, supplier, onDone }: { rfq: Rfq; supplier: RfqSupplier; onDone: (r: Rfq) => void }) {
  const [open, setOpen] = React.useState(false)
  const [reason, setReason] = React.useState('')
  const decline = useMutation({ mutationFn: () => declineRfq(rfq.id, supplier.rfq_vendor_id, reason.trim()), onSuccess: (r) => { onDone(r); setOpen(false) } })
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="size-8" aria-label={`More for ${supplier.name}`}><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => setOpen(true)}><X className="size-4" />Will not quote</DropdownMenuItem></DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{supplier.name} will not quote</DialogTitle></DialogHeader>
          <div className="flex flex-col gap-1.5"><Label htmlFor="decline-reason">Why <span className="font-normal text-muted-foreground">(optional)</span></Label><Input id="decline-reason" autoFocus value={reason} placeholder="No stock of 12 mm" onChange={(e) => setReason(e.target.value)} /></div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Back</Button><Button disabled={decline.isPending} onClick={() => decline.mutate()}>Mark declined</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function GstLine({ q }: { q: QuoteCell }) {
  if (!q.gst_known) return <span>GST not said</span>
  if (Number(q.gst_percent) === 0) return <span>No GST</span>
  return <span>{rate(q.rate_entered)} {q.rate_includes_gst ? 'incl.' : '+'} {q.gst_percent}%{q.gst_claimable ? ' · claimable' : ''}</span>
}

function Delta({ pct }: { pct: string | null | undefined }) {
  if (pct === null || pct === undefined) return null
  const n = Number(pct)
  if (Math.abs(n) < 0.5) return <span className="text-muted-foreground">same as last</span>
  return (
    <span className={cn('inline-flex items-center gap-0.5 font-semibold', n > 0 ? 'text-destructive' : 'text-emerald-700 dark:text-emerald-400')}>
      {n > 0 ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}{n > 0 ? '+' : ''}{pct}% vs last
    </span>
  )
}

function CompareSheet({ rfq, picks, onPick }: { rfq: Rfq; picks: Record<string, string>; onPick?: (line: string, rv: string) => void }) {
  const isMobile = useIsMobile()
  const suppliers = rfq.suppliers.filter((s) => s.status === 'quoted')
  const scores = useSupplierScores()  // PRC-50
  const cell = (line: RfqLine, s: RfqSupplier) => line.quotes.find((q) => q.rfq_vendor_id === s.rfq_vendor_id)
  const awarded = (line: RfqLine, q: QuoteCell | undefined) => !!q && line.awarded_quote_line_id === q.quote_line_id

  if (isMobile) {
    return (
      <div className="flex flex-col gap-3">
        {rfq.lines.map((line) => (
          <div key={line.id} className="overflow-hidden rounded-xl border">
            <div className="flex items-center gap-2 bg-muted/40 px-3 py-2">
              <CategoryTile mainCategory={line.main_category} size="sm" />
              <span className="min-w-0 flex-1 truncate font-semibold">{line.material}</span>
              <span className="text-sm tabular-nums text-muted-foreground">{Number(line.quantity).toLocaleString('en-IN')} {line.unit}</span>
            </div>
            {line.last_paid && <p className="px-3 pt-2 text-xs text-muted-foreground">Last paid {rate(line.last_paid.rate)}/{line.unit} · {line.last_paid.vendor_name}, {day(line.last_paid.date)}</p>}
            <ul className="flex flex-col gap-1.5 p-2">
              {suppliers.map((s) => {
                const q = cell(line, s)
                const on = picks[line.id] === s.rfq_vendor_id
                return (
                  <li key={s.rfq_vendor_id}>
                    <button type="button" disabled={!q || !onPick} onClick={() => q && onPick?.(line.id, s.rfq_vendor_id)} className={cn('flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left', q?.lowest && 'border-emerald-400 bg-emerald-50 dark:bg-emerald-950/40', on && 'ring-2 ring-yellow-400', !q && 'opacity-50')}>
                      <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{s.name}</span><span className="block text-[11px] text-muted-foreground">{q ? <GstLine q={q} /> : 'Not quoted'}</span></span>
                      {q && <span className="text-right"><span className="block font-semibold tabular-nums">{rate(q.cost)}</span><span className="block text-[11px]"><Delta pct={q.vs_last_paid_pct} /></span></span>}
                      {awarded(line, q) && <CheckCircle2 className="size-4 text-teal-600" />}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="bg-muted/40 text-left">
            <th className="sticky left-0 z-10 bg-muted/40 px-3 py-2 font-semibold">Item</th>
            {suppliers.map((s) => (
              <th key={s.rfq_vendor_id} className={cn('px-3 py-2 text-right font-semibold', s.best_total && 'text-emerald-700 dark:text-emerald-400')}>
                <span className="inline-flex items-center gap-1">{s.best_total && <Crown className="size-3.5" />}{s.name}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rfq.lines.map((line) => (
            <tr key={line.id} className="border-t align-top">
              <td className="sticky left-0 z-10 bg-background px-3 py-2.5">
                <span className="flex items-center gap-2"><CategoryTile mainCategory={line.main_category} size="sm" /><span><span className="block font-semibold">{line.material}</span><span className="block text-xs text-muted-foreground tabular-nums">{Number(line.quantity).toLocaleString('en-IN')} {line.unit}</span></span></span>
                {line.last_paid && <span className="mt-1 block text-[11px] text-muted-foreground">Last paid {rate(line.last_paid.rate)} · {line.last_paid.vendor_name}</span>}
                {line.award_reason && <span className="mt-1 block text-[11px] text-muted-foreground">Chosen because: {line.award_reason}</span>}
              </td>
              {suppliers.map((s) => {
                const q = cell(line, s)
                const on = picks[line.id] === s.rfq_vendor_id
                return (
                  <td key={s.rfq_vendor_id} className="p-1.5 text-right">
                    {q ? (
                      <button type="button" disabled={!onPick} onClick={() => onPick?.(line.id, s.rfq_vendor_id)} aria-pressed={on}
                        title={onPick ? 'Pick this supplier for this item' : undefined}
                        className={cn('flex w-full flex-col items-end gap-0.5 rounded-lg border border-transparent px-2 py-1.5 transition', onPick && 'hover:border-foreground/20',
                          q.lowest && 'bg-emerald-50 dark:bg-emerald-950/40', q.highest && 'bg-red-50/70 dark:bg-red-950/30', on && 'ring-2 ring-yellow-400', awarded(line, q) && 'ring-2 ring-teal-500')}>
                        <span className="flex items-center gap-1.5">
                          {q.lowest && <span className="rounded bg-emerald-600 px-1 text-[10px] font-bold text-white">LOWEST</span>}
                          {awarded(line, q) && <CheckCircle2 className="size-3.5 text-teal-600" />}
                          <span className={cn('text-base font-semibold tabular-nums', q.lowest && 'text-emerald-800 dark:text-emerald-300', q.highest && 'text-destructive')}>{rate(q.cost)}</span>
                        </span>
                        <span className="text-[11px] text-muted-foreground"><GstLine q={q} /></span>
                        <span className="text-[11px] tabular-nums text-muted-foreground">{rupees(q.amount)}{q.brand ? ` · ${q.brand}` : ''}</span>
                        <span className="text-[11px]"><Delta pct={q.vs_last_paid_pct} /></span>
                      </button>
                    ) : <span className="block px-2 py-3 text-xs text-muted-foreground">Not quoted</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t-2 bg-muted/20 text-xs">
          <Foot label="Total (as it costs you)" suppliers={suppliers} value={(s) => <span className={cn('text-sm font-bold tabular-nums', s.best_total && 'text-emerald-700 dark:text-emerald-400')}>{rupees(s.total)}{!s.complete && <span className="block text-[10px] font-normal text-muted-foreground">{s.lines_quoted} of {rfq.lines.length} items</span>}</span>} />
          <Foot label="You pay (with GST)" suppliers={suppliers} value={(s) => <span className="tabular-nums">{rupees(s.total_with_gst)}</span>} />
          <Foot label="Delivery" suppliers={suppliers} value={(s) => (s.delivery_days != null ? `${s.delivery_days} day${s.delivery_days === 1 ? '' : 's'}` : '—')} />
          <Foot label="Credit" suppliers={suppliers} value={(s) => (s.payment_days != null ? `${s.payment_days} days` : '—')} />
          <Foot label="Valid until" suppliers={suppliers} value={(s) => (s.valid_until ? day(s.valid_until) : '—')} />
          <Foot label="Cheapest on" suppliers={suppliers} value={(s) => `${s.lines_lowest} of ${rfq.lines.length}`} />
          <Foot label="Supplier score" suppliers={suppliers} value={(s) => <ScoreChip p={scores.get(s.vendor_id)} className="text-xs" />} />
        </tfoot>
      </table>
    </div>
  )
}

function Foot({ label, suppliers, value }: { label: string; suppliers: RfqSupplier[]; value: (s: RfqSupplier) => React.ReactNode }) {
  return (
    <tr className="border-t">
      <th className="sticky left-0 bg-muted/20 px-3 py-1.5 text-left font-medium text-muted-foreground">{label}</th>
      {suppliers.map((s) => <td key={s.rfq_vendor_id} className="px-3.5 py-1.5 text-right">{value(s)}</td>)}
    </tr>
  )
}

function WaysToBuy({ rfq, picks, onAward }: { rfq: Rfq; picks: Record<string, string>; onAward?: (p: AwardPayload) => void }) {
  const one = rfq.lowest_total
  const per = rfq.lowest_per_line
  const picked = Object.entries(picks).filter(([, rv]) => rv)
  const vendorOf = (rv: string) => rfq.suppliers.find((s) => s.rfq_vendor_id === rv)!
  return (
    <div className="flex flex-col gap-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className={cn('flex flex-col gap-1 rounded-xl border p-3', one && (!per?.saves || Number(per.saves) <= 0) && 'border-emerald-400')}>
          <span className="text-xs font-semibold text-muted-foreground uppercase">All from one supplier</span>
          {one ? <><span className="text-lg font-semibold tabular-nums">{rupees(one.total)}</span><span className="text-sm">{one.name} · one delivery to follow</span></>
            : <span className="text-sm text-muted-foreground">Nobody quoted every item yet.</span>}
          {one && onAward && <Button size="sm" variant="outline" className="mt-1 w-fit gap-1.5" onClick={() => onAward({ mode: 'lowest_total' })}><ShoppingCart className="size-3.5" />Order all from {one.name}</Button>}
        </div>
        <div className={cn('flex flex-col gap-1 rounded-xl border p-3', per?.saves && Number(per.saves) > 0 && 'border-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/30')}>
          <span className="text-xs font-semibold text-muted-foreground uppercase">Cheapest per item</span>
          {per ? <>
            <span className="text-lg font-semibold tabular-nums">{rupees(per.total)}{!per.complete && <span className="text-xs font-normal text-muted-foreground"> · not every item quoted</span>}</span>
            <span className="text-sm">{per.suppliers} supplier{per.suppliers === 1 ? '' : 's'}{per.saves && Number(per.saves) > 0 ? <> · <strong className="text-emerald-700 dark:text-emerald-400">saves {rupees(per.saves)}</strong> but {per.suppliers} deliveries</> : ''}</span>
          </> : <span className="text-sm text-muted-foreground">No quotes yet.</span>}
          {per && onAward && per.suppliers > 1 && <Button size="sm" className="mt-1 w-fit gap-1.5 font-semibold" onClick={() => onAward({ mode: 'lowest_per_line' })}><PackagePlus className="size-3.5" />Order the cheapest per item</Button>}
        </div>
      </div>
      {onAward && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed px-3 py-2 text-sm">
          <span className="text-muted-foreground">{picked.length ? <>Picked: {picked.map(([line, rv]) => `${rfq.lines.find((l) => l.id === line)?.material} from ${vendorOf(rv).name}`).join('; ')}</> : 'Or tap a rate in the sheet to choose the supplier for that item yourself.'}</span>
          {picked.length > 0 && <Button size="sm" className="gap-1.5 font-semibold" onClick={() => onAward({ mode: 'picks', picks: picked.map(([line, rv]) => ({ rfq_line_id: line, vendor_id: vendorOf(rv).vendor_id })) })}><ShoppingCart className="size-3.5" />Order picked ({picked.length})</Button>}
        </div>
      )}
    </div>
  )
}

/** What the award will order, per supplier, before anything is placed; asks why when it is not the cheapest. */
function plan(rfq: Rfq, p: AwardPayload): { supplier: RfqSupplier; items: { line: RfqLine; q: QuoteCell }[] }[] {
  const chosen: { line: RfqLine; q: QuoteCell }[] = []
  if (p.mode === 'lowest_total' && rfq.lowest_total) {
    for (const line of rfq.lines) { const q = line.quotes.find((x) => x.rfq_vendor_id === rfq.lowest_total!.rfq_vendor_id); if (q) chosen.push({ line, q }) }
  } else if (p.mode === 'lowest_per_line') {
    for (const line of rfq.lines) if (line.quotes[0]) chosen.push({ line, q: line.quotes[0] })
  } else {
    for (const pick of p.picks ?? []) {
      const line = rfq.lines.find((l) => l.id === pick.rfq_line_id)!
      const rv = rfq.suppliers.find((s) => s.vendor_id === pick.vendor_id)!.rfq_vendor_id
      const q = line.quotes.find((x) => x.rfq_vendor_id === rv)
      if (q) chosen.push({ line, q })
    }
  }
  const by = new Map<string, { line: RfqLine; q: QuoteCell }[]>()
  for (const c of chosen) by.set(c.q.rfq_vendor_id, [...(by.get(c.q.rfq_vendor_id) ?? []), c])
  return [...by.entries()].map(([rv, items]) => ({ supplier: rfq.suppliers.find((s) => s.rfq_vendor_id === rv)!, items }))
}

function AwardDialog({ rfq, payload, onClose, onDone }: { rfq: Rfq; payload: AwardPayload | null; onClose: () => void; onDone: (r: Rfq) => void }) {
  const [reason, setReason] = React.useState('')
  const [duplicate, setDuplicate] = React.useState('')
  const [error, setError] = React.useState('')
  React.useEffect(() => { setReason(''); setDuplicate(''); setError('') }, [payload])
  const groups = payload ? plan(rfq, payload) : []
  const notCheapest = groups.flatMap((g) => g.items.filter((i) => !i.q.lowest && i.line.quotes.length > 1 && i.line.quotes[0].rfq_vendor_id !== i.q.rfq_vendor_id).map((i) => i.line.material))
  const award = useMutation({
    mutationFn: (confirm: boolean) => awardRfq(rfq.id, { ...payload!, reason: reason.trim() || null, confirm_duplicate: confirm }),
    onSuccess: (r) => { onDone(r); onClose() },
    onError: (err) => {
      const dup = asDuplicateConflict(err)
      if (dup) return setDuplicate(dup.message)
      const why = asReasonNeeded(err)
      if (why) return setError(why.message)
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Not ordered. Try again.')
    },
  })
  const total = groups.reduce((s, g) => s + g.items.reduce((t, i) => t + Number(i.q.amount ?? 0), 0), 0)
  return (
    <Dialog open={!!payload} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Place {groups.length} order{groups.length === 1 ? '' : 's'} from {rfq.ref}</DialogTitle></DialogHeader>
        <div className="flex flex-col gap-2">
          {groups.map((g) => (
            <div key={g.supplier.rfq_vendor_id} className="rounded-xl border p-3">
              <div className="mb-1.5 flex items-center gap-2"><VendorTile id={g.supplier.vendor_id} name={g.supplier.name} /><span className="flex-1 font-semibold">{g.supplier.name}</span>{g.supplier.delivery_days != null && <span className="text-xs text-muted-foreground">expected in {g.supplier.delivery_days}d</span>}</div>
              <ul className="flex flex-col gap-0.5 pl-[52px] text-sm">
                {g.items.map((i) => <li key={i.line.id} className="flex justify-between gap-2"><span>{i.line.material} · {Number(i.line.quantity).toLocaleString('en-IN')} {i.line.unit}</span><span className="tabular-nums">{rate(i.q.rate_entered)}{i.q.gst_known && Number(i.q.gst_percent) > 0 ? ` ${i.q.rate_includes_gst ? 'incl.' : '+'} ${i.q.gst_percent}%` : ''}</span></li>)}
              </ul>
            </div>
          ))}
          <p className="text-sm text-muted-foreground">Costs you <strong className="text-foreground tabular-nums">{rupees(total)}</strong>. Each order goes to Purchase orders; the site's request is marked ordered and whoever asked is told.</p>
          {notCheapest.length > 0 && (
            <div className="flex flex-col gap-1.5 rounded-xl border border-amber-300 bg-amber-50 p-3 dark:bg-amber-950/40">
              <Label htmlFor="award-reason">Not the cheapest for {notCheapest.join(', ')}: why?</Label>
              <div className="flex flex-wrap gap-1.5">{['Better quality', 'Delivers sooner', 'Gives credit', 'Brand asked for'].map((w) => <button key={w} type="button" onClick={() => setReason(w)} className={cn('h-7 rounded-full border px-2.5 text-xs', reason === w ? 'border-foreground bg-foreground text-background' : 'bg-background')}>{w}</button>)}</div>
              <Input id="award-reason" value={reason} maxLength={300} placeholder="Their reason, kept on the RFQ" onChange={(e) => setReason(e.target.value)} />
            </div>
          )}
          {duplicate && (
            <div className="flex flex-col gap-2 rounded-xl border border-orange-300 bg-orange-50 p-3 text-sm text-orange-950 dark:bg-orange-950 dark:text-orange-100">
              <span><strong>Already on order.</strong> {duplicate}</span>
              <Button size="sm" className="w-fit bg-orange-600 text-white hover:bg-orange-700" disabled={award.isPending} onClick={() => award.mutate(true)}>It is extra, order anyway</Button>
            </div>
          )}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Back</Button>
          <Button className="font-semibold" disabled={award.isPending || (notCheapest.length > 0 && !reason.trim()) || !!duplicate} onClick={() => award.mutate(false)}>Place order{groups.length === 1 ? '' : 's'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EndDialog({ rfq, kind, onClose, onDone }: { rfq: Rfq; kind: 'close' | 'cancel' | null; onClose: () => void; onDone: (r: Rfq) => void }) {
  const [reason, setReason] = React.useState('')
  React.useEffect(() => setReason(''), [kind])
  const end = useMutation({ mutationFn: () => closeRfq(rfq.id, kind!, reason.trim()), onSuccess: (r) => { onDone(r); onClose() } })
  return (
    <Dialog open={!!kind} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{kind === 'close' ? `Close ${rfq.ref} without ordering` : `Cancel ${rfq.ref}`}</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">{kind === 'close' ? 'The quotes stay, for Rates and each supplier’s price list.' : 'Nobody is ordered from it.'}</p>
        <div className="flex flex-col gap-1.5"><Label htmlFor="end-reason">Why</Label><Input id="end-reason" autoFocus value={reason} placeholder={kind === 'close' ? 'Prices only, for the budget' : 'Not needed any more'} onChange={(e) => setReason(e.target.value)} /></div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Back</Button><Button disabled={end.isPending} onClick={() => end.mutate()}>{kind === 'close' ? 'Close' : 'Cancel RFQ'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
