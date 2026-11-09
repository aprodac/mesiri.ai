import * as React from 'react'
import { LinkedStrip } from '@/components/page/page-kit'
import { raBillLinks } from '@/lib/links'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BadgeCheck, FilePlus2, Printer, ReceiptText, ScrollText, Send, Share2, Trash2, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, PageError } from '@/components/dpr-page'
import { ContractDialog } from '@/components/billing/contract-dialog'
import { ProjectPickList, usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import {
  BILL_STATUS, billDay, certifyRaBill, createRaBill, deleteRaBill, fetchContract, fetchRaBill, fetchRaBills, mayBill, qty,
  raBillAction, rupees, setRaBillQuantity, type RaBill, type RaBillLine,
} from '@/lib/billing'
import { cn } from '@/lib/utils'
import { ModuleTitle } from '@/components/page/page-kit'

// NXT-02: Client billing › RA bills. A bill is made from the BOQ: work measured on each priced line (the site's own
// WhatsApp updates) less what earlier bills already billed, at the client rate. The contract's retention, advance
// recovery, GST and TDS are worked out on it. The office may change a quantity before submitting (the measured one
// stays visible); a submitted bill is frozen and printed on the letterhead; the client's certified amount is noted.

const NUM = 'text-right tabular-nums'

export default function RaBillsPage() {
  usePageTitle('RA bills')
  const { me } = useAuth()
  const projectId = usePlanningProject()
  const allowed = mayBill(me?.role)
  return (
    <div className="mx-auto flex w-full min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center gap-3">
        <ModuleTitle icon={ReceiptText} title="RA bills" />
      </header>
      {!allowed ? (
        <p className="text-sm text-muted-foreground">Client bills are for the owner, admins and finance.</p>
      ) : !projectId ? (
        <>
          <p className="text-sm text-muted-foreground">Pick the project to bill.</p>
          <ProjectPickList to={(id) => `/billing/ra-bills?project=${id}`} empty="No projects yet." />
        </>
      ) : (
        <ProjectBills key={projectId} projectId={projectId} />
      )}
    </div>
  )
}

function ProjectBills({ projectId }: { projectId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [contractOpen, setContractOpen] = React.useState(false)
  const contract = useQuery({ queryKey: ['contract', projectId], queryFn: () => fetchContract(projectId) })
  const list = useQuery({ queryKey: ['ra-bills', projectId], queryFn: () => fetchRaBills(projectId) })
  const selected = params.get('bill') ?? list.data?.[0]?.id ?? null
  const pick = (id: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (id) n.set('bill', id); else n.delete('bill'); return n })

  const create = useMutation({
    mutationFn: () => createRaBill(projectId),
    onSuccess: (b) => {
      queryClient.invalidateQueries({ queryKey: ['ra-bills'] })
      pick(b.id)
      toast.success(`${b.ref} drafted from the measured work`)
    },
    onError: (e) => toast.error('Could not make the bill', apiErrorMessage(e)),
  })

  if (list.isError) return <PageError message="The bills did not load." onRetry={() => list.refetch()} back={{ to: '/billing/ra-bills', label: 'All projects' }} />
  const c = contract.data?.contract
  const hasDraft = list.data?.some((b) => b.status === 'draft')

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">{contract.data?.project.name ?? '…'}</p>
          <p className="text-sm text-muted-foreground">
            {c ? [c.client_name ?? 'No client set', c.contract_value && `contract ${rupees(c.contract_value)}`,
              `retention ${Number(c.retention_pct ?? 0)}%`, c.mobilisation_advance && `advance ${rupees(c.mobilisation_advance)} (${Number(c.advance_recovery_pct ?? 0)}% a bill)`,
              `GST ${Number(c.gst_pct ?? 0)}%`, `TDS ${Number(c.tds_pct ?? 0)}%`].filter(Boolean).join(' · ') : 'No contract terms yet'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setContractOpen(true)}><ScrollText className="size-4" /> Contract terms</Button>
          <Button size="sm" variant="outline" className="gap-1.5" asChild><Link to={`/billing/client-view?project=${projectId}`}><Share2 className="size-4" /> Share with client</Link></Button>
          <Button size="sm" className="gap-1.5" disabled={create.isPending || hasDraft || !c} onClick={() => create.mutate()} title={!c ? 'Set the contract terms first' : hasDraft ? 'Submit or remove the draft first' : undefined}>
            <FilePlus2 className="size-4" /> New RA bill
          </Button>
        </div>
      </div>
      {!c && (
        <Callout tone="info" icon={ScrollText} action={<Button size="sm" onClick={() => setContractOpen(true)}>Set the terms</Button>}>
          Set the client and the contract's retention, advance, GST and TDS first: every bill works them out from these.
        </Callout>
      )}
      {!list.data ? (
        <Skeleton className="h-48 w-full" />
      ) : list.data.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          No bills yet. “New RA bill” takes the work site has measured on each priced BOQ line and prices it at the client rate.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
          <ul className="flex gap-2 overflow-x-auto lg:flex-col">
            {list.data.map((b) => (
              <li key={b.id}>
                <button type="button" onClick={() => pick(b.id)}
                  className={cn('w-full min-w-44 rounded-lg border p-3 text-left text-sm', selected === b.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/50')}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{b.ref}</span>
                    <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', BILL_STATUS[b.status].tone)}>{BILL_STATUS[b.status].label}</span>
                  </span>
                  <span className="block text-muted-foreground">{billDay(b.bill_date)}</span>
                  <span className="block font-medium tabular-nums">{rupees(b.net)} net</span>
                </button>
              </li>
            ))}
          </ul>
          {selected && <BillView key={selected} billId={selected} onRemoved={() => pick(null)} />}
        </div>
      )}
      <ContractDialog projectId={projectId} open={contractOpen} onOpenChange={setContractOpen} />
    </>
  )
}

function BillView({ billId, onRemoved }: { billId: string; onRemoved: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['ra-bill', billId], queryFn: () => fetchRaBill(billId) })
  const [certifying, setCertifying] = React.useState(false)
  const put = (b: RaBill) => {
    queryClient.setQueryData(['ra-bill', billId], b)
    queryClient.invalidateQueries({ queryKey: ['ra-bills'] })
  }
  const fail = (title: string) => (e: unknown) => toast.error(title, apiErrorMessage(e))
  const setQty = useMutation({ mutationFn: (v: { line: RaBillLine; q: string }) => setRaBillQuantity(billId, v.line.id, v.q), onSuccess: put, onError: fail('Could not change the quantity') })
  const act = useMutation({
    mutationFn: (a: 'submit' | 'cancel') => raBillAction(billId, a),
    onSuccess: (b) => { put(b); toast.success(b.status === 'submitted' ? `${b.ref} submitted: print it for the client` : `${b.ref} withdrawn`) },
    onError: fail('Could not do that'),
  })
  const remove = useMutation({
    mutationFn: () => deleteRaBill(billId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['ra-bills'] }); onRemoved(); toast.success('Draft removed') },
    onError: fail('Could not remove the draft'),
  })
  const b = query.data
  if (!b) return <Skeleton className="h-64 w-full" />
  const draft = b.status === 'draft'
  const rows: [string, string | null, string?][] = [
    ['Work this bill', b.gross],
    [`GST ${Number(b.gst_pct)}%`, b.gst, '+'],
    [`Retention ${Number(b.retention_pct)}%`, b.retention, '−'],
    [`Advance recovery ${Number(b.advance_recovery_pct)}%`, b.advance_recovery, '−'],
    [`TDS ${Number(b.tds_pct)}%`, b.tds, '−'],
  ]

  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{b.ref} <span className={cn('ml-1 rounded-full px-2 py-0.5 align-middle text-[11px] font-semibold', BILL_STATUS[b.status].tone)}>{BILL_STATUS[b.status].label}</span></h2>
          <p className="text-sm text-muted-foreground">
            {billDay(b.bill_date)}{b.client_name ? ` · to ${b.client_name}` : ''}
            {b.certified_amount && ` · certified ${rupees(b.certified_amount, 2)} on ${billDay(b.certified_on)}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" asChild className="gap-1.5"><Link to={`/billing/ra-bills/${b.id}/document`}><Printer className="size-4" /> {draft ? 'Preview' : 'Print / PDF'}</Link></Button>
          {draft && <Button size="sm" className="gap-1.5" disabled={act.isPending} onClick={() => act.mutate('submit')}><Send className="size-4" /> Submit</Button>}
          {draft && <Button size="sm" variant="ghost" className="gap-1.5 text-destructive" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 className="size-4" /> Remove</Button>}
          {(b.status === 'submitted' || b.status === 'certified') && <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setCertifying(true)}><BadgeCheck className="size-4" /> {b.status === 'certified' ? 'Change certified' : 'Certified by client'}</Button>}
          {b.status === 'submitted' && <Button size="sm" variant="ghost" className="gap-1.5" disabled={act.isPending} onClick={() => act.mutate('cancel')}><Undo2 className="size-4" /> Withdraw</Button>}
        </div>
      </div>
      {!!b.warnings?.length && (
        <Callout tone="draft" icon={AlertTriangle}>
          <ul className="flex flex-col gap-1">{b.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
        </Callout>
      )}
      {draft && <p className="text-xs text-muted-foreground">Quantities are what site measured since the last bill. Change one if the client's engineer measured differently; the measured figure stays shown.</p>}

      <div className="overflow-x-auto rounded-lg border [contain:inline-size]">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Work</th>
              <th className={cn('px-2 py-2 font-medium', NUM)}>Measured to date</th>
              <th className={cn('px-2 py-2 font-medium', NUM)}>Earlier bills</th>
              <th className={cn('px-2 py-2 font-medium', NUM)}>This bill</th>
              <th className={cn('px-2 py-2 font-medium', NUM)}>Rate</th>
              <th className={cn('px-3 py-2 font-medium', NUM)}>Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {b.lines?.map((ln) => (
              <tr key={ln.id}>
                <td className="px-3 py-2"><span className="text-muted-foreground">{ln.boq_code ? `${ln.boq_code} ` : ''}</span>{ln.work}</td>
                <td className={cn('px-2 py-2', NUM)}>{qty(ln.measured_to_date)} {ln.unit}</td>
                <td className={cn('px-2 py-2', NUM)}>{qty(ln.previous_quantity)}</td>
                <td className={cn('px-2 py-2', NUM)}>
                  {draft ? (
                    <QtyInput line={ln} onSave={(q) => setQty.mutate({ line: ln, q })} />
                  ) : qty(ln.quantity)}
                  {ln.edited && <span className="block text-[11px] text-draft">measured {qty(ln.suggested_quantity)}</span>}
                </td>
                <td className={cn('px-2 py-2', NUM)}>{rupees(ln.client_rate, 2)}</td>
                <td className={cn('px-3 py-2 font-medium', NUM)}>{rupees(ln.amount, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="ml-auto grid w-full max-w-sm gap-1 text-sm">
        {rows.map(([label, value, sign]) => (
          <div key={label} className="flex justify-between gap-4">
            <dt className="text-muted-foreground">{sign ? `${sign} ` : ''}{label}</dt>
            <dd className="tabular-nums">{rupees(value, 2)}</dd>
          </div>
        ))}
        <div className="mt-1 flex justify-between gap-4 border-t pt-2 text-base font-semibold">
          <dt>Net payable</dt>
          <dd className="tabular-nums">{rupees(b.net, 2)}</dd>
        </div>
        {b.certified_amount && b.net && Number(b.certified_amount) !== Number(b.net) && (
          <p className="text-xs text-draft">Client certified {rupees(Number(b.certified_amount) - Number(b.net), 2)} against the net.</p>
        )}
      </dl>
      <CertifyDialog bill={b} open={certifying} onOpenChange={setCertifying} onSaved={put} />
      <LinkedStrip records={raBillLinks(b)} className="border-t pt-3" />
    </section>
  )
}

function QtyInput({ line, onSave }: { line: RaBillLine; onSave: (q: string) => void }) {
  const [v, setV] = React.useState(String(Number(line.quantity)))
  React.useEffect(() => setV(String(Number(line.quantity))), [line.quantity])
  const commit = () => { if (v.trim() !== '' && Number(v) >= 0 && Number(v) !== Number(line.quantity)) onSave(v.trim()) }
  return (
    <Input aria-label={`This bill for ${line.work}`} inputMode="decimal" className="ml-auto h-8 w-24 text-right" value={v}
      onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit() }} />
  )
}

function CertifyDialog({ bill, open, onOpenChange, onSaved }: { bill: RaBill; open: boolean; onOpenChange: (o: boolean) => void; onSaved: (b: RaBill) => void }) {
  const toast = useToast()
  const [amount, setAmount] = React.useState('')
  const [on, setOn] = React.useState('')
  React.useEffect(() => { if (open) { setAmount(String(Number(bill.certified_amount ?? bill.net ?? 0))); setOn(bill.certified_on ?? '') } }, [open, bill])
  const save = useMutation({
    mutationFn: () => certifyRaBill(bill.id, { certified_amount: amount, certified_on: on || undefined }),
    onSuccess: (b) => { onSaved(b); toast.success(`${b.ref} certified`); onOpenChange(false) },
    onError: (e) => toast.error('Could not save', apiErrorMessage(e)),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{bill.ref} certified by the client</DialogTitle>
          <DialogDescription>The amount the client's engineer passed. When it differs from the bill, the difference is shown.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1"><Label htmlFor="cert-amt">Certified amount (₹)</Label><Input id="cert-amt" type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
          <div className="grid gap-1"><Label htmlFor="cert-on">Certified on</Label><Input id="cert-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={save.isPending || amount === '' || Number(amount) < 0} onClick={() => save.mutate()}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
