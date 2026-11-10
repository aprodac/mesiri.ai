import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, CheckCircle2, FileText, Image, Truck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SheetTitle } from '@/components/ui/sheet'
import { CategoryTile } from '@/components/requests/parts'
import { VendorLink } from '@/components/vendors/vendor-parts'
import { rupees } from '@/lib/orders'
import { RETURN_LOOK, cancelReturn, fetchReturnPhotos, markReturnSent, settleReturn, type MaterialReturn } from '@/lib/returns'
import { qty } from '@/lib/site-day'
import { cn } from '@/lib/utils'

// PRC-46: one return in the Requests / Purchase orders panel look: the debit note's figure, what went back and why,
// the timeline (recorded -> sent back -> settled), and the next step (sent back, settle, cancel) for the office.

function day(d: string): string {
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export function ReturnDetail({ ret: r, inSheet }: { ret: MaterialReturn; inSheet?: boolean }) {
  const queryClient = useQueryClient()
  const [step, setStep] = React.useState<'' | 'sent' | 'settle' | 'cancel'>('')
  const [who, setWho] = React.useState('')
  const [how, setHow] = React.useState<'replacement' | 'credit'>('replacement')
  const [note, setNote] = React.useState('')
  const [error, setError] = React.useState('')
  const [hint, setHint] = React.useState('')
  const [photos, setPhotos] = React.useState<string[] | null>(null)
  const look = RETURN_LOOK[r.status]
  const done = (got: MaterialReturn) => {
    queryClient.invalidateQueries({ queryKey: ['procurement', 'returns'] })
    queryClient.invalidateQueries({ queryKey: ['vendors'] })
    queryClient.invalidateQueries({ queryKey: ['materials'] })
    setStep('')
    setNote('')
    setHint(got.hint ?? '')
  }
  const fail = (err: unknown) => {
    const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    setError(typeof d === 'string' ? d : 'That did not save.')
  }
  const act = useMutation({
    mutationFn: () =>
      step === 'sent' ? markReturnSent(r.id, { collected_by: who.trim() || null })
        : step === 'settle' ? settleReturn(r.id, { how, note: note.trim() || null })
          : cancelReturn(r.id, note.trim()),
    onSuccess: done,
    onError: fail,
  })
  const Title = inSheet ? SheetTitle : 'h2'

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 border-b p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Title className="text-lg leading-tight font-semibold">{r.ref} · <VendorLink id={r.vendor_id} name={r.vendor_name} /></Title>
            <p className="truncate text-sm text-muted-foreground">{r.project_name} › {r.site_name} · {day(r.returned_on)}{r.grn_ref ? ` · from ${r.grn_ref}` : ''}{r.order_ref ? ` (${r.order_ref})` : ''}</p>
          </div>
          <span className={cn('inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold', look.chip)}><span className={cn('size-1.5 rounded-full', look.dot)} />{look.label}</span>
        </div>
        {r.total !== undefined && (
          <div className="flex items-end justify-between gap-3 rounded-xl bg-orange-50 px-3 py-2.5 dark:bg-orange-950/40">
            <span className="text-sm text-orange-950 dark:text-orange-100">{r.status === 'settled' ? 'The supplier owed you' : r.status === 'cancelled' ? 'Was' : 'The supplier owes you'}</span>
            <span className="text-right">
              <span className="block text-2xl font-semibold tabular-nums">{rupees(r.total)}</span>
              {Number(r.gst) > 0 && <span className="block text-xs text-muted-foreground">{rupees(r.before_gst)} + GST {rupees(r.gst)}</span>}
            </span>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {r.status !== 'cancelled' && (
            <Button asChild variant="outline" className="gap-2"><Link to={`/procurement/returns/${r.id}/document`}><FileText className="size-4" /> Debit note</Link></Button>
          )}
          {r.photos > 0 && (
            <Button variant="outline" className="gap-2" onClick={async () => setPhotos(await fetchReturnPhotos(r.id))}><Image className="size-4" /> {r.photos} {r.photos === 1 ? 'photo' : 'photos'}</Button>
          )}
          {r.may_send && <Button className="gap-2 font-semibold" onClick={() => { setError(''); setStep('sent') }}><Truck className="size-4" /> Sent back</Button>}
          {r.may_settle && <Button variant={r.may_send ? 'outline' : 'default'} className="gap-2 font-semibold" onClick={() => { setError(''); setStep('settle') }}><CheckCircle2 className="size-4" /> Settled</Button>}
          {r.may_cancel && <Button variant="ghost" className="gap-2 text-muted-foreground" onClick={() => { setError(''); setStep('cancel') }}><Ban className="size-4" /> Cancel</Button>}
        </div>
        {photos && (
          <div className="flex flex-wrap gap-2">
            {photos.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer"><img src={u} alt="Returned material" className="h-20 w-20 rounded-lg border object-cover" /></a>)}
            {photos.length === 0 && <span className="text-xs text-muted-foreground">The photos cannot be opened right now.</span>}
          </div>
        )}
        {step && (
          <form className="flex flex-col gap-2 rounded-xl border p-3" onSubmit={(e) => { e.preventDefault(); act.mutate() }}>
            {step === 'sent' && (
              <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
                Collected by (optional)
                <Input value={who} onChange={(e) => setWho(e.target.value)} placeholder="Their driver, lorry number" className="text-sm text-foreground" />
              </label>
            )}
            {step === 'settle' && (
              <div role="radiogroup" aria-label="How it was settled" className="grid grid-cols-2 gap-2">
                {([['replacement', 'They sent a replacement'], ['credit', 'Credit on their bill']] as const).map(([v, label]) => (
                  <button key={v} type="button" role="radio" aria-checked={how === v} onClick={() => setHow(v)} className={cn('rounded-lg border px-3 py-2 text-left text-sm', how === v && 'border-yellow-500 bg-yellow-50 font-semibold dark:bg-yellow-950')}>{label}</button>
                ))}
              </div>
            )}
            {(step === 'settle' || step === 'cancel') && (
              <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
                {step === 'cancel' ? 'Why is it not going back?' : 'Note (optional)'}
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={step === 'cancel' ? 'They exchanged it at the site' : 'Bill 1182 is ₹8,400 less'} className="text-sm text-foreground" />
              </label>
            )}
            {step === 'cancel' && <p className="text-xs text-muted-foreground">What it took from stock goes back, and the debit note leaves their account.</p>}
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={act.isPending || (step === 'cancel' && !note.trim())}>{act.isPending ? 'Saving…' : step === 'cancel' ? 'Cancel the return' : 'Save'}</Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setStep('')}>Back</Button>
            </div>
          </form>
        )}
        {(hint || r.hint) && <p className="rounded-lg bg-yellow-50 px-3 py-2 text-sm text-yellow-950 dark:bg-yellow-950 dark:text-yellow-100">{hint || r.hint}{r.order_id && <> <Link className="font-semibold underline" to={`/procurement/orders?id=${r.order_id}`}>Open {r.order_ref}</Link></>}</p>}
      </div>

      <section className="flex flex-col gap-2 border-b px-4 py-3 sm:px-5">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">What went back</h3>
        {r.lines.map((l) => (
          <div key={l.id} className="flex items-center gap-3 rounded-lg border px-3 py-2">
            <CategoryTile mainCategory={l.main_category} size="sm" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{l.material}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {l.reason_label}{l.from_stock ? ' · out of stock' : ' · rejected at the gate, never in stock'}{l.receipt_date ? ` · delivered ${day(l.receipt_date)}` : ''}
              </span>
            </span>
            <span className="flex shrink-0 flex-col items-end">
              <span className="text-sm font-semibold tabular-nums">{qty(l.quantity)} {l.unit}</span>
              {l.amount && <span className="text-xs text-muted-foreground tabular-nums">{rupees(l.amount)}</span>}
            </span>
          </div>
        ))}
        {!!r.unpriced_lines && <p className="text-xs text-muted-foreground">{r.unpriced_lines} {r.unpriced_lines === 1 ? 'line has' : 'lines have'} no rate, so the debit note leaves {r.unpriced_lines === 1 ? 'it' : 'them'} out.</p>}
        {r.notes && <p className="text-sm text-muted-foreground">“{r.notes}”</p>}
      </section>

      <section className="flex flex-col gap-2 px-4 py-3 sm:px-5">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Timeline</h3>
        <ol className="relative flex flex-col gap-3 border-l pl-4">
          {r.timeline.map((t, i) => (
            <li key={i} className="relative">
              <span className={cn('absolute top-1.5 -left-[21px] size-2.5 rounded-full border-2 border-background', i === r.timeline.length - 1 ? look.dot : 'bg-muted-foreground/40')} />
              <span className="block text-sm">{t.what}</span>
              <span className="block text-xs text-muted-foreground">{day(t.on)}{t.by ? ` · ${t.by}` : ''}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
