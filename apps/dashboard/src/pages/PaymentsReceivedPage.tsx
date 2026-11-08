import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HandCoins, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { usePlanningProject } from '@/components/schedule/project-picker'
import { useAuth } from '@/lib/AuthContext'
import {
  billDay, deleteClientPayment, fetchClientPayments, fetchReceivables, mayBill, PAYMENT_KINDS, recordClientPayment, rupees,
  type PaymentKind, type ProjectReceivable,
} from '@/lib/billing'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// END-02: Client billing › Payments received (also Accounts › Receivables). What each client still owes on the RA
// bills, oldest first; retention held and the day it falls due (handover + defect liability months); the advance
// still to come; and every payment received. "Client paid 6 lakh for RA-3" on WhatsApp records the same payment.

const NUM = 'text-right tabular-nums'
const SELECT = 'h-9 w-full rounded-md border bg-background px-2 text-sm'

export default function PaymentsReceivedPage() {
  usePageTitle('Payments received')
  const { me } = useAuth()
  const allowed = mayBill(me?.role)
  const projectId = usePlanningProject()
  const readOnly = useReadOnly()
  const rec = useQuery({ queryKey: ['receivables', projectId], queryFn: () => fetchReceivables(projectId), enabled: allowed })
  const pays = useQuery({ queryKey: ['client-payments', projectId], queryFn: () => fetchClientPayments(projectId), enabled: allowed })
  const [paying, setPaying] = React.useState<ProjectReceivable | null>(null)

  return (
    <div className="mx-auto flex w-full max-w-5xl min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center gap-3">
        <span className="inline-flex size-10 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"><HandCoins className="size-5" /></span>
        <div>
          <div className="text-xs text-muted-foreground">Client billing</div>
          <h1 className="text-2xl leading-tight font-semibold tracking-tight">Payments received</h1>
        </div>
      </header>
      {!allowed ? (
        <p className="text-sm text-muted-foreground">Client payments are for the owner, admins and finance.</p>
      ) : rec.isError ? (
        <PageError message="The receivables did not load." onRetry={() => rec.refetch()} back={{ to: '/billing/ra-bills', label: 'RA bills' }} />
      ) : !rec.data ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Tile label="Clients owe on bills" value={rupees(rec.data.outstanding)} bad={Number(rec.data.outstanding) > 0} />
            <Tile label="Retention held by clients" value={rupees(rec.data.retention_left)} />
            <Tile label="Received so far" value={rupees(rec.data.received)} />
          </div>
          {rec.data.projects.length === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              Nothing billed yet. Submitted <Link className="underline underline-offset-2" to="/billing/ra-bills">RA bills</Link> show here with what the client still owes.
            </p>
          ) : rec.data.projects.map((p) => (
            <ProjectMoney key={p.project.id} p={p} canPay={!readOnly} onPay={() => setPaying(p)} />
          ))}
          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">Payments</h2>
            {!pays.data ? <Skeleton className="h-24 w-full" /> : pays.data.length === 0 ? (
              <p className="text-sm text-muted-foreground">None recorded yet.</p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[40rem] text-sm">
                  <thead className="bg-muted/50 text-xs text-muted-foreground">
                    <tr><th className="p-2 text-left">Day</th><th className="p-2 text-left">Project</th><th className="p-2 text-left">For</th><th className="p-2 text-left">How</th><th className={cn('p-2', NUM)}>Amount</th><th className="p-2" /></tr>
                  </thead>
                  <tbody className="divide-y">
                    {pays.data.map((x) => <PaymentRow key={x.id} id={x.id} day={x.received_on} project={x.project_name}
                      what={x.bill_ref ?? x.kind_label} how={[x.mode, x.reference].filter(Boolean).join(' · ')} amount={x.amount} canDelete={!readOnly} />)}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      <PaymentDialog p={paying} onClose={() => setPaying(null)} />
    </div>
  )
}

function Tile({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-xl border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('text-xl font-semibold tabular-nums', bad && 'text-red-700 dark:text-red-300')}>{value}</p>
    </div>
  )
}

function ProjectMoney({ p, canPay, onPay }: { p: ProjectReceivable; canPay: boolean; onPay: () => void }) {
  const retention = Number(p.retention_left) > 0
  return (
    <section className="flex flex-col gap-2 rounded-xl border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{p.project.name}</p>
          <p className="text-xs text-muted-foreground">
            {[p.client?.name ?? 'No client set', p.contract_value && `contract ${rupees(p.contract_value)}`, `billed ${rupees(p.billed)}`, `received ${rupees(p.received)}`].filter(Boolean).join(' · ')}
          </p>
        </div>
        {canPay && <Button size="sm" className="gap-1.5" onClick={onPay}><Plus className="size-4" /> Payment received</Button>}
      </div>
      {p.bills.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="py-1 text-left">Bill</th><th className="py-1 text-left">Date</th><th className={cn('py-1', NUM)}>Due</th><th className={cn('py-1', NUM)}>Received</th><th className={cn('py-1', NUM)}>Still owed</th></tr>
            </thead>
            <tbody className="divide-y">
              {p.bills.map((b) => (
                <tr key={b.id}>
                  <td className="py-1.5"><Link className="font-medium underline-offset-2 hover:underline" to={`/billing/ra-bills?project=${p.project.id}&bill=${b.id}`}>{b.ref}</Link>{b.status === 'certified' && <span className="ml-1 text-xs text-success">certified</span>}</td>
                  <td className="py-1.5">{billDay(b.bill_date)}</td>
                  <td className={cn('py-1.5', NUM)}>{rupees(b.due)}</td>
                  <td className={cn('py-1.5', NUM)}>{rupees(b.received)}</td>
                  <td className={cn('py-1.5 font-medium', NUM, Number(b.outstanding) > 0 && b.age_days > 30 && 'text-red-700 dark:text-red-300')}>
                    {Number(b.outstanding) === 0 ? 'Paid' : rupees(b.outstanding)}
                    {Number(b.outstanding) > 0 && <span className="block text-[11px] font-normal text-muted-foreground">{b.age_days} days</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {retention
          ? <>Retention held {rupees(p.retention_left)}{p.retention_due_on ? `, due ${billDay(p.retention_due_on)}` : p.handed_over_on ? ' (set the defect liability months in the contract)' : ', due after the defect period (set the handover day)'}{p.retention_due_now && <strong className="text-red-700 dark:text-red-300"> · due now: ask for it</strong>}</>
          : 'No retention held.'}
        {p.has_advance && ` · Advance ${rupees(p.advance_received)} of ${rupees(p.advance)} received`}
      </p>
    </section>
  )
}

function PaymentRow({ id, day, project, what, how, amount, canDelete }: { id: string; day: string; project: string; what: string; how: string; amount: string; canDelete: boolean }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => deleteClientPayment(id),
    onSuccess: () => {
      for (const k of ['receivables', 'client-payments', 'handover']) queryClient.invalidateQueries({ queryKey: [k] })
      toast.success('Payment removed')
    },
    onError: (e) => toast.error('Not removed', apiErrorMessage(e)),
  })
  return (
    <tr>
      <td className="p-2">{billDay(day)}</td>
      <td className="p-2">{project}</td>
      <td className="p-2">{what}</td>
      <td className="p-2 text-muted-foreground">{how || '—'}</td>
      <td className={cn('p-2 font-medium', NUM)}>{rupees(amount, 2)}</td>
      <td className="p-2 text-right">{canDelete && <Button size="sm" variant="ghost" aria-label="Remove the payment" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 className="size-3.5" /></Button>}</td>
    </tr>
  )
}

function PaymentDialog({ p, onClose }: { p: ProjectReceivable | null; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const owed = React.useMemo(() => p?.bills.filter((b) => Number(b.outstanding) > 0) ?? [], [p])
  const [form, setForm] = React.useState<Record<string, string>>({})
  React.useEffect(() => {
    if (!p) return
    const first = owed[0]
    setForm({ kind: first ? 'bill' : 'other', bill_id: first?.id ?? '', amount: first ? String(Number(first.outstanding)) : '', received_on: '', mode: 'Bank transfer', reference: '' })
  }, [p, owed])
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const save = useMutation({
    mutationFn: () => recordClientPayment(p!.project.id, {
      kind: form.kind as PaymentKind, bill_id: form.kind === 'bill' ? form.bill_id || null : null, amount: form.amount,
      received_on: form.received_on || undefined, mode: form.mode || null, reference: form.reference.trim() || null,
    }),
    onSuccess: (r) => {
      for (const k of ['receivables', 'client-payments', 'handover']) queryClient.invalidateQueries({ queryKey: [k] })
      toast.success(`${rupees(r.payment.amount)} recorded`, `${rupees(r.receivable.outstanding)} still owed on ${r.receivable.project.name}'s bills`)
      onClose()
    },
    onError: (e) => toast.error('Not recorded', apiErrorMessage(e)),
  })
  const ready = Number(form.amount) > 0 && (form.kind !== 'bill' || !!form.bill_id)
  return (
    <Dialog open={!!p} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Payment received</DialogTitle>
          <DialogDescription>{p?.project.name}{p?.client ? ` · ${p.client.name}` : ''}</DialogDescription>
        </DialogHeader>
        <form id="pay-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          <div className="grid gap-1">
            <Label htmlFor="pay-kind">For</Label>
            <select id="pay-kind" className={SELECT} value={form.kind ?? 'bill'} onChange={set('kind')}>
              {PAYMENT_KINDS.map((k) => <option key={k.key} value={k.key} disabled={k.key === 'bill' && owed.length === 0}>{k.label}</option>)}
            </select>
          </div>
          {form.kind === 'bill' && (
            <div className="grid gap-1">
              <Label htmlFor="pay-bill">Bill</Label>
              <select id="pay-bill" className={SELECT} value={form.bill_id ?? ''} onChange={(e) => {
                const b = owed.find((x) => x.id === e.target.value)
                setForm((f) => ({ ...f, bill_id: e.target.value, amount: b ? String(Number(b.outstanding)) : f.amount }))
              }}>
                {owed.map((b) => <option key={b.id} value={b.id}>{b.ref}: {rupees(b.outstanding)} still owed</option>)}
              </select>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1">
              <Label htmlFor="pay-amount">Amount (₹)</Label>
              <Input id="pay-amount" inputMode="decimal" required value={form.amount ?? ''} onChange={set('amount')} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="pay-on">Received on</Label>
              <Input id="pay-on" type="date" value={form.received_on ?? ''} onChange={set('received_on')} />
            </div>
            <div className="grid gap-1">
              <Label htmlFor="pay-mode">How</Label>
              <select id="pay-mode" className={SELECT} value={form.mode ?? ''} onChange={set('mode')}>
                {['Bank transfer', 'UPI', 'Cheque', 'Cash'].map((m) => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div className="grid gap-1">
              <Label htmlFor="pay-ref">Reference</Label>
              <Input id="pay-ref" placeholder="UTR or cheque no." value={form.reference ?? ''} onChange={set('reference')} />
            </div>
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="pay-form" disabled={save.isPending || !ready}>{save.isPending ? 'Saving…' : 'Record'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
