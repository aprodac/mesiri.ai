import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, FileText, GitMerge, Landmark, Link2, Wallet } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchAccountsApi } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { rupees } from '@/lib/expenses'
import { cn } from '@/lib/utils'
import {
  KINDS,
  PAY_METHODS,
  allocate,
  billDeliveries,
  createVendor,
  day,
  fetchLedger,
  fetchVendors,
  linkName,
  matchDeliveries,
  mergeVendor,
  num,
  payVendor,
  updateVendor,
  type LedgerLine,
  type UnlinkedName,
  type Vendor,
  type VendorKind,
} from '@/lib/vendors'

// CC-09 / CC-10: the supplier dialogs. Add or edit a supplier (kind, credit days, contact, opening balance), pay one
// (oldest bills first, the rest as an advance, with a preview of what it pays), bill deliveries already recorded, put
// deliveries on a bill typed earlier, merge two records of the same supplier.

const todayIso = () => new Date().toISOString().slice(0, 10)

function Field({ label, htmlFor, hint, children, className }: { label: string; htmlFor?: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={htmlFor} className="text-sm font-medium">{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null
  return <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{apiErrorMessage(error)}</p>
}

// --- Add / edit ----------------------------------------------------------------------------------------------------

export function VendorFormDialog({ open, onOpenChange, vendor, canSetOpening, onSaved, initialName }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  vendor: Vendor | null
  canSetOpening: boolean
  onSaved?: (v: Vendor) => void
  initialName?: string
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [f, setF] = React.useState({ name: '', kind: 'supplier' as VendorKind, phone: '', gstin: '', address: '', contact_person: '', credit_days: '', notes: '', opening: '', opening_side: 'owe' as 'owe' | 'ahead', opening_date: todayIso() })
  React.useEffect(() => {
    if (!open) return
    const ob = num(vendor?.opening_balance)
    setF({
      name: vendor?.name ?? initialName ?? '', kind: vendor?.kind ?? 'supplier', phone: vendor?.phone ?? '', gstin: vendor?.gstin ?? '',
      address: vendor?.address ?? '', contact_person: vendor?.contact_person ?? '', credit_days: vendor?.credit_days != null ? String(vendor.credit_days) : '',
      notes: vendor?.notes ?? '', opening: ob ? String(Math.abs(ob)) : '', opening_side: ob < 0 ? 'ahead' : 'owe', opening_date: vendor?.opening_balance_date ?? todayIso(),
    })
  }, [open, vendor, initialName])
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF((x) => ({ ...x, [k]: e.target.value }))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name.trim(), kind: f.kind, phone: f.phone.trim() || null, gstin: f.gstin.trim() || null, address: f.address.trim() || null,
        contact_person: f.contact_person.trim() || null, credit_days: f.credit_days === '' ? null : Number(f.credit_days), notes: f.notes.trim() || null,
        ...(canSetOpening
          ? f.opening === ''
            ? vendor?.opening_balance != null ? { opening_balance: null, opening_balance_date: null } : {}
            : { opening_balance: String(f.opening_side === 'ahead' ? -Number(f.opening) : Number(f.opening)), opening_balance_date: f.opening_date }
          : {}),
      }
      return vendor ? updateVendor(vendor.id, body) : createVendor(body)
    },
    onSuccess: (v) => {
      queryClient.invalidateQueries({ queryKey: ['finance'] })
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
      toast.success(vendor ? `${v.name} saved` : `${v.name} added`)
      onSaved?.(v)
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{vendor ? `Edit ${vendor.name}` : 'Add a supplier'}</DialogTitle>
          <DialogDescription>Shops, subcontractors, hire companies and services the company pays.</DialogDescription>
        </DialogHeader>
        <form id="vendor-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (f.name.trim()) save.mutate() }}>
          <Field label="Name" htmlFor="v-name">
            <Input id="v-name" required autoFocus value={f.name} onChange={set('name')} placeholder="Malabar Hardware" />
          </Field>
          <div role="radiogroup" aria-label="Kind" className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            {(Object.keys(KINDS) as VendorKind[]).map((k) => (
              <button key={k} type="button" role="radio" aria-checked={f.kind === k} onClick={() => setF((x) => ({ ...x, kind: k }))}
                className={cn('h-9 rounded-lg border text-sm', f.kind === k ? 'border-primary bg-primary/10 font-semibold' : 'hover:bg-muted')}>
                {KINDS[k].label}
              </button>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Phone" htmlFor="v-phone"><Input id="v-phone" inputMode="tel" value={f.phone} onChange={set('phone')} placeholder="98470 12345" /></Field>
            <Field label="Contact person" htmlFor="v-contact"><Input id="v-contact" value={f.contact_person} onChange={set('contact_person')} placeholder="Shaji" /></Field>
            <Field label="GSTIN" htmlFor="v-gstin"><Input id="v-gstin" value={f.gstin} maxLength={20} className="uppercase" onChange={(e) => setF((x) => ({ ...x, gstin: e.target.value.toUpperCase() }))} placeholder="32ABCDE1234F1Z5" /></Field>
            <Field label="Credit (days to pay)" htmlFor="v-credit" hint="A bill is overdue after this many days.">
              <Input id="v-credit" type="number" min={0} max={365} inputMode="numeric" value={f.credit_days} onChange={set('credit_days')} placeholder="30" />
            </Field>
          </div>
          <Field label="Address" htmlFor="v-address"><Input id="v-address" value={f.address} onChange={set('address')} placeholder="Edappally, Kochi" /></Field>
          {canSetOpening && (
            <fieldset className="grid gap-2 rounded-lg border bg-muted/30 p-3">
              <legend className="px-1 text-sm font-medium">Opening balance</legend>
              <p className="text-xs text-muted-foreground">What stood with them before you started in Mesiri. The account starts on this date: older bills and payments are inside this figure.</p>
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <Input type="number" min={0} step="any" inputMode="decimal" aria-label="Opening amount" value={f.opening} onChange={set('opening')} placeholder="0" className="bg-background" />
                <Select value={f.opening_side} onValueChange={(v) => setF((x) => ({ ...x, opening_side: v as 'owe' | 'ahead' }))}>
                  <SelectTrigger className="w-[150px] bg-background" aria-label="Who owes"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="owe">We owe them</SelectItem>
                    <SelectItem value="ahead">We paid ahead</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Input type="date" aria-label="As of" value={f.opening_date} max={todayIso()} onChange={set('opening_date')} className="bg-background dark:[color-scheme:dark]" />
            </fieldset>
          )}
          <Field label="Notes" htmlFor="v-notes">
            <textarea id="v-notes" rows={2} value={f.notes} onChange={set('notes')} placeholder="Delivers only after 2 pm; cheque in the name of…" className="rounded-md border bg-background px-3 py-2 text-sm" />
          </Field>
          <ErrorLine error={save.error} />
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="vendor-form" disabled={!f.name.trim() || save.isPending} className="font-semibold">
            {save.isPending ? 'Saving…' : vendor ? 'Save' : 'Add supplier'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Pay -----------------------------------------------------------------------------------------------------------

interface Account { id: string; name: string; account_type: string; current_balance: number | string; status?: string }

export function PayVendorDialog({ open, onOpenChange, vendor, preselect, projectId }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  vendor: Pick<Vendor, 'id' | 'name'>
  preselect?: string[]
  projectId?: string | null
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  // The open bills and balance, read here so every entry point (the list, the supplier page, an expense) pays alike.
  const ledger = useQuery({ queryKey: ['finance', 'ledger', vendor.id, projectId ?? ''], queryFn: () => fetchLedger(vendor.id, { project_id: projectId ?? undefined }), enabled: open })
  const bills = React.useMemo(() => ledger.data?.summary.open_bills ?? [], [ledger.data])
  const balance = num(ledger.data?.closing)
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'payable'], queryFn: () => fetchAccountsApi(), enabled: open, staleTime: 30_000 })
  const active = ((accounts.data ?? []) as Account[]).filter((a) => a.status !== 'inactive' && !a.name.startsWith('TDS payable'))
  const [account, setAccount] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [date, setDate] = React.useState(todayIso())
  const [method, setMethod] = React.useState<string>('Bank transfer')
  const [reference, setReference] = React.useState('')
  const [mode, setMode] = React.useState<'oldest' | 'pick' | 'advance'>('oldest')
  const [picked, setPicked] = React.useState<string[]>([])

  React.useEffect(() => {
    if (!open || !ledger.data) return
    const pre = preselect?.length ? preselect : []
    setPicked(pre)
    setMode(pre.length ? 'pick' : bills.length ? 'oldest' : 'advance')
    const due = pre.length ? bills.filter((b) => pre.includes(b.id)).reduce((n, b) => n + num(b.left), 0) : Math.max(balance, 0)
    setAmount(due > 0 ? String(Math.round(due * 100) / 100) : '')
    setDate(todayIso())
    setReference('')
  }, [open, preselect, bills, balance, ledger.data])
  React.useEffect(() => {
    if (!account && active.length) setAccount(String((active.find((a) => a.account_type === 'bank') ?? active[0]).id))
  }, [active, account])
  React.useEffect(() => {
    const a = active.find((x) => String(x.id) === account)
    if (a) setMethod(a.account_type === 'cash' || a.account_type === 'employee_advance' ? 'Cash' : (m) => (m === 'Cash' ? 'Bank transfer' : m))
  }, [account]) // eslint-disable-line react-hooks/exhaustive-deps

  const order = mode === 'pick' ? bills.filter((b) => picked.includes(b.id)) : mode === 'oldest' ? bills : []
  const plan = allocate(Number(amount) || 0, order)
  const used = plan.reduce((n, p) => n + p.part, 0)
  const extra = Math.max(0, (Number(amount) || 0) - used)
  const chosen = active.find((a) => String(a.id) === account)
  const short = chosen && Number(chosen.current_balance) < (Number(amount) || 0)

  const pay = useMutation({
    mutationFn: () => payVendor(vendor.id, {
      account_id: account, amount: String(Number(amount)), paid_date: date, method, reference: reference.trim() || undefined,
      project_id: projectId ?? undefined, bill_ids: mode === 'oldest' ? undefined : mode === 'pick' ? picked : [],
    }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['finance'] })
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
      const paid = r.bills_paid.length ? `Pays ${r.bills_paid.length} ${r.bills_paid.length === 1 ? 'bill' : 'bills'}` : 'Kept as an advance'
      toast.success(`${rupees(num(r.amount))} paid to ${r.vendor} from ${r.account}`, num(r.advance_left) ? `${paid}; ${rupees(num(r.advance_left))} stays with them for the next bill.` : `${paid}.`)
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Pay {vendor.name}</DialogTitle>
          <DialogDescription>{!ledger.data ? 'Reading what is owed…' : balance > 0 ? `You owe ${rupees(balance)}.` : balance < 0 ? `They already hold ${rupees(-balance)} of yours.` : 'Nothing is owed: this will be an advance.'}</DialogDescription>
        </DialogHeader>
        {active.length === 0 && accounts.isSuccess ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">Add a bank account or petty cash in Finance › Money first: a payment says which account the money left.</p>
        ) : (
          <form id="pay-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (account && Number(amount) > 0) pay.mutate() }}>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Amount" htmlFor="pay-amount">
                <Input id="pay-amount" type="number" min={0} step="any" inputMode="decimal" required value={amount} onChange={(e) => setAmount(e.target.value)} className="text-lg font-semibold tabular-nums" />
              </Field>
              <Field label="Paid on" htmlFor="pay-date">
                <Input id="pay-date" type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} className="dark:[color-scheme:dark]" />
              </Field>
            </div>
            <Field label="From">
              <Select value={account} onValueChange={setAccount}>
                <SelectTrigger aria-label="Paid from which account"><SelectValue placeholder="Which account" /></SelectTrigger>
                <SelectContent>
                  {active.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      <span className="inline-flex items-center gap-2">
                        {a.account_type === 'bank' ? <Landmark className="size-3.5 text-sky-700" /> : <Wallet className="size-3.5 text-amber-700" />}
                        {a.name} · {rupees(Number(a.current_balance) || 0)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {short && <p className="text-xs text-draft">{chosen?.name} has {rupees(Number(chosen?.current_balance) || 0)}: it will go below zero.</p>}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="How">
                <Select value={method} onValueChange={setMethod}>
                  <SelectTrigger aria-label="How it was paid"><SelectValue /></SelectTrigger>
                  <SelectContent>{PAY_METHODS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Reference" htmlFor="pay-ref"><Input id="pay-ref" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="UTR / cheque no." /></Field>
            </div>

            {bills.length > 0 && (
              <fieldset className="grid gap-2">
                <legend className="mb-1 text-sm font-medium">Pays which bills</legend>
                <div role="radiogroup" className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1 text-sm">
                  {([['oldest', 'Oldest first'], ['pick', 'Pick bills'], ['advance', 'Advance only']] as const).map(([v, l]) => (
                    <button key={v} type="button" role="radio" aria-checked={mode === v} onClick={() => setMode(v)} className={cn('h-8 rounded-md', mode === v ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}>{l}</button>
                  ))}
                </div>
                {mode === 'pick' && (
                  <ul className="max-h-48 divide-y overflow-y-auto rounded-lg border">
                    {bills.map((b) => {
                      const on = picked.includes(b.id)
                      return (
                        <li key={b.id}>
                          <label className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-muted/40">
                            <input type="checkbox" checked={on} className="size-4 accent-primary" onChange={() => {
                              const next = on ? picked.filter((x) => x !== b.id) : [...picked, b.id]
                              setPicked(next)
                              setAmount(String(bills.filter((x) => next.includes(x.id)).reduce((n, x) => n + num(x.left), 0)))
                            }} />
                            <span className="min-w-0 flex-1 truncate">{b.bill_number ? `Bill ${b.bill_number}` : b.description || b.number} · {day(b.date)}</span>
                            {b.overdue_days > 0 && <span className="text-xs font-semibold text-destructive">{b.overdue_days}d late</span>}
                            <span className="font-medium tabular-nums">{rupees(num(b.left))}</span>
                          </label>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </fieldset>
            )}

            {Number(amount) > 0 && (
              <div className="grid gap-1 rounded-lg border bg-muted/30 p-3 text-sm" aria-live="polite">
                {plan.map((p) => (
                  <div key={p.bill.id} className="flex items-center gap-2">
                    <CircleCheck className={cn('size-4 shrink-0', p.part >= num(p.bill.left) ? 'text-success' : 'text-amber-600')} />
                    <span className="min-w-0 flex-1 truncate">{p.bill.bill_number ? `Bill ${p.bill.bill_number}` : p.bill.description || p.bill.number}{p.part < num(p.bill.left) ? ' (part)' : ''}</span>
                    <span className="tabular-nums">{rupees(p.part)}</span>
                  </div>
                ))}
                {extra > 0 && (
                  <div className="flex items-center gap-2 text-sky-800 dark:text-sky-300">
                    <ArrowRight className="size-4 shrink-0" />
                    <span className="flex-1">Stays with them as an advance for the next bill</span>
                    <span className="tabular-nums">{rupees(extra)}</span>
                  </div>
                )}
              </div>
            )}
            <ErrorLine error={pay.error} />
          </form>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="pay-form" disabled={!account || !(Number(amount) > 0) || pay.isPending || (mode === 'pick' && !picked.length)} className="font-semibold">
            {pay.isPending ? 'Saving…' : `Pay ${Number(amount) > 0 ? rupees(Number(amount)) : ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Bill deliveries / put deliveries on a bill --------------------------------------------------------------------

export function BillDeliveriesDialog({ open, onOpenChange, vendor, deliveries, bills }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  vendor: Vendor
  deliveries: LedgerLine[]
  /** Every bill of this supplier (paid or not) a delivery may be put on: a bill typed without its deliveries. */
  bills: { id: string; label: string }[]
}) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const total = deliveries.reduce((n, d) => n + num(d.owe), 0)
  const projects = new Set(deliveries.map((d) => d.project_id))
  const [mode, setMode] = React.useState<'new' | 'existing'>('new')
  const [amount, setAmount] = React.useState('')
  const [number, setNumber] = React.useState('')
  const [date, setDate] = React.useState(todayIso())
  const [gst, setGst] = React.useState('')
  const [bill, setBill] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setMode('new')
    setAmount(String(Math.round(total * 100) / 100))
    setNumber('')
    setDate(todayIso())
    setGst('')
    setBill('')
  }, [open, total])
  const diff = (Number(amount) || 0) - total
  const done = (what: string) => {
    queryClient.invalidateQueries({ queryKey: ['finance'] })
    queryClient.invalidateQueries({ queryKey: ['vendors'] })
    toast.success(what, 'From now on they are owed and counted once, through the bill.')
    onOpenChange(false)
  }
  const save = useMutation({
    mutationFn: () => mode === 'new'
      ? billDeliveries(vendor.id, { receipt_ids: deliveries.map((d) => d.links.receipt_id!), amount: amount || undefined, bill_number: number.trim() || undefined, bill_date: date, tax_amount: gst || undefined }).then(() => `Bill recorded for ${deliveries.length} ${deliveries.length === 1 ? 'delivery' : 'deliveries'}`)
      : matchDeliveries(vendor.id, bill, deliveries.map((d) => d.links.receipt_id!)).then(() => `${deliveries.length} ${deliveries.length === 1 ? 'delivery' : 'deliveries'} put on the bill`),
    onSuccess: done,
  })
  const tooMany = mode === 'new' && projects.size > 1

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{deliveries.length} {deliveries.length === 1 ? 'delivery' : 'deliveries'} from {vendor.name}</DialogTitle>
          <DialogDescription>Worth {rupees(total)} at the rates recorded on site. The bill takes their place: owed and counted once.</DialogDescription>
        </DialogHeader>
        <ul className="max-h-36 divide-y overflow-y-auto rounded-lg border text-sm">
          {deliveries.map((d) => (
            <li key={d.id} className="flex items-center gap-2 px-3 py-1.5">
              <span className="w-14 shrink-0 text-xs text-muted-foreground">{day(d.date)}</span>
              <span className="min-w-0 flex-1 truncate">{d.title}{d.site ? ` · ${d.site}` : ''}</span>
              <span className="tabular-nums">{rupees(num(d.owe))}</span>
            </li>
          ))}
        </ul>
        <div role="radiogroup" className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1 text-sm">
          <button type="button" role="radio" aria-checked={mode === 'new'} onClick={() => setMode('new')} className={cn('inline-flex h-8 items-center justify-center gap-1.5 rounded-md', mode === 'new' ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}><FileText className="size-4" /> Record their bill</button>
          <button type="button" role="radio" aria-checked={mode === 'existing'} disabled={!bills.length} onClick={() => setMode('existing')} className={cn('inline-flex h-8 items-center justify-center gap-1.5 rounded-md disabled:opacity-50', mode === 'existing' ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75')}><Link2 className="size-4" /> Already recorded</button>
        </div>
        <form id="bill-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          {mode === 'new' ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Bill amount" htmlFor="b-amount" hint={Math.abs(diff) >= 1 ? `${diff > 0 ? '+' : '−'}${rupees(Math.abs(diff))} against the deliveries (GST, freight…)` : 'Same as the deliveries'}>
                  <Input id="b-amount" type="number" min={0} step="any" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-semibold tabular-nums" />
                </Field>
                <Field label="GST in it" htmlFor="b-gst"><Input id="b-gst" type="number" min={0} step="any" inputMode="decimal" value={gst} onChange={(e) => setGst(e.target.value)} placeholder="0" /></Field>
                <Field label="Their bill number" htmlFor="b-no"><Input id="b-no" value={number} onChange={(e) => setNumber(e.target.value)} placeholder="MH/2231" /></Field>
                <Field label="Bill date" htmlFor="b-date"><Input id="b-date" type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} className="dark:[color-scheme:dark]" /></Field>
              </div>
              {tooMany && <p className="text-sm text-draft">These are from {projects.size} projects: a bill belongs to one project. Pick one project's deliveries.</p>}
            </>
          ) : (
            <Field label="Which bill" hint="A bill typed as an expense without its deliveries.">
              <Select value={bill} onValueChange={setBill}>
                <SelectTrigger><SelectValue placeholder="Pick the bill" /></SelectTrigger>
                <SelectContent>
                  {bills.map((b) => <SelectItem key={b.id} value={b.id}>{b.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
          )}
          <ErrorLine error={save.error} />
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="bill-form" className="font-semibold" disabled={save.isPending || tooMany || (mode === 'existing' && !bill) || (mode === 'new' && !(Number(amount) > 0))}>
            {save.isPending ? 'Saving…' : mode === 'new' ? 'Record bill' : 'Put on this bill'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Merge ---------------------------------------------------------------------------------------------------------

export function MergeVendorDialog({ open, onOpenChange, vendor, onMerged }: { open: boolean; onOpenChange: (o: boolean) => void; vendor: Vendor; onMerged: (into: Vendor) => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const list = useQuery({ queryKey: ['vendors', 'all'], queryFn: fetchVendors, enabled: open })
  const [q, setQ] = React.useState('')
  const [into, setInto] = React.useState('')
  React.useEffect(() => { if (open) { setQ(''); setInto('') } }, [open])
  const words = vendor.name.toLowerCase().split(/\s+/)[0]
  const others = (list.data ?? []).filter((v) => v.id !== vendor.id)
    .filter((v) => !q.trim() || v.name.toLowerCase().includes(q.trim().toLowerCase()))
    .sort((a, b) => Number(b.name.toLowerCase().includes(words)) - Number(a.name.toLowerCase().includes(words)) || a.name.localeCompare(b.name))
  const target = others.find((v) => v.id === into)
  const merge = useMutation({
    mutationFn: () => mergeVendor(vendor.id, into),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['finance'] })
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
      const m = r.moved
      toast.success(`${vendor.name} merged into ${r.into.name}`, `Moved ${m.expenses} expenses, ${m.deliveries} deliveries, ${m.orders} orders, ${m.payments} payments.`)
      onOpenChange(false)
      onMerged(r.into)
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><GitMerge className="size-5" /> Merge {vendor.name}</DialogTitle>
          <DialogDescription>The same supplier saved twice. Everything of {vendor.name} moves to the one you pick, and {vendor.name} is removed. Missing phone, GSTIN or address are copied over.</DialogDescription>
        </DialogHeader>
        <Input autoFocus placeholder="Search suppliers" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search suppliers" />
        <ul className="max-h-60 divide-y overflow-y-auto rounded-lg border">
          {others.slice(0, 50).map((v) => (
            <li key={v.id}>
              <button type="button" onClick={() => setInto(v.id)} className={cn('flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/40', into === v.id && 'bg-primary/10 font-semibold')}>
                <span className="min-w-0 flex-1 truncate">{v.name}</span>
                <span className="text-xs text-muted-foreground">{KINDS[v.kind ?? 'supplier'].label}{v.status !== 'active' ? ' · off' : ''}</span>
              </button>
            </li>
          ))}
          {list.isSuccess && !others.length && <li className="px-3 py-4 text-center text-sm text-muted-foreground">No other supplier matches.</li>}
        </ul>
        <ErrorLine error={merge.error} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!into || merge.isPending} onClick={() => merge.mutate()} className="font-semibold">
            {merge.isPending ? 'Merging…' : target ? `Merge into ${target.name}` : 'Merge'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Supplier names on no account ----------------------------------------------------------------------------------

export function LinkNamesDialog({ open, onOpenChange, names }: { open: boolean; onOpenChange: (o: boolean) => void; names: UnlinkedName[] }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const vendors = useQuery({ queryKey: ['vendors', 'all'], queryFn: fetchVendors, enabled: open })
  const [choice, setChoice] = React.useState<Record<string, string>>({})
  React.useEffect(() => {
    if (open) setChoice(Object.fromEntries(names.map((n) => [n.name, n.likely?.id ?? 'new'])))
  }, [open, names])
  const save = useMutation({
    mutationFn: async (name: string) => {
      const pick = choice[name]
      return linkName(pick === 'new' ? { name, create: true } : { name, vendor_id: pick })
    },
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['finance'] })
      queryClient.invalidateQueries({ queryKey: ['vendors'] })
      toast.success(`${r.deliveries} ${r.deliveries === 1 ? 'delivery' : 'deliveries'} now on ${r.vendor.name}'s account`)
    },
    onError: (e) => toast.error('Not linked', apiErrorMessage(e)),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Supplier names on no account</DialogTitle>
          <DialogDescription>Deliveries saved with these names point at no supplier, so they are on nobody's account, rates or bills. Pick the supplier each is, or add it.</DialogDescription>
        </DialogHeader>
        <ul className="divide-y rounded-lg border">
          {names.map((n) => (
            <li key={n.name} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">“{n.name}”</span>
                <span className="block text-xs text-muted-foreground">{n.deliveries} {n.deliveries === 1 ? 'delivery' : 'deliveries'}{n.amount ? ` · ${rupees(num(n.amount))}` : ''}{n.last ? ` · last ${day(n.last)}` : ''}</span>
              </span>
              <Select value={choice[n.name] ?? 'new'} onValueChange={(v) => setChoice((c) => ({ ...c, [n.name]: v }))}>
                <SelectTrigger className="h-8 w-[180px]" aria-label={`Supplier for ${n.name}`}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="new">Add “{n.name}” as a supplier</SelectItem>
                  {(vendors.data ?? []).map((v) => <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(n.name)}>Link</Button>
            </li>
          ))}
        </ul>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Done</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
