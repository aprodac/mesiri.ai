import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CircleCheck, ListPlus, Plus, Trash2 } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useToast } from '@/components/ui/toast-notification'
import { fetchAccountsApi } from '@/lib/api'
import { fetchBoq } from '@/lib/boq'
import { fetchProjects, fetchSites } from '@/lib/projects'
import { apiErrorMessage } from '@/lib/logo-upload'
import { rupees } from '@/lib/expenses'
import { fetchVendors, PAY_METHODS } from '@/lib/vendors'
import { cn } from '@/lib/utils'
import {
  addMeasurement, checkBill, createWorkOrder, decideBill, editWorkOrder, giveAdvance, n, recordBill, releaseRetention,
  type BillCheck, type LineIn, type WoBill, type WorkOrder,
} from '@/lib/subcontracts'

// NXT-05/06/07: the subcontract dialogs. A work order (subcontractor, where, lines from the BOQ or typed, retention,
// advance, TDS, terms); a measurement; a bill with its check and deductions shown live before it is saved; approve or
// reject a flagged bill with a reason; an advance; releasing retention.

const today = () => new Date().toISOString().slice(0, 10)
const UNITS = ['cum', 'sqm', 'sqft', 'rmt', 'rft', 'nos', 'kg', 'MT', 'LS', 'day']

function Field({ label, htmlFor, hint, children, className }: { label: string; htmlFor?: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={htmlFor} className="text-sm font-medium">{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function Err({ error }: { error: unknown }) {
  return error ? <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{apiErrorMessage(error)}</p> : null
}

function useDone() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ['subcontracts'] })
    queryClient.invalidateQueries({ queryKey: ['finance'] })
    queryClient.invalidateQueries({ queryKey: ['vendors'] })
  }
}

// --- Work order ----------------------------------------------------------------------------------------------------

interface DraftLine extends LineIn { key: string; boq_label?: string }

export function WorkOrderDialog({ open, onOpenChange, editing, preset, onSaved }: {
  open: boolean
  onOpenChange: (o: boolean) => void
  editing?: WorkOrder | null
  preset?: { project_id?: string; site_id?: string; vendor_id?: string; vendor_name?: string }
  onSaved?: (wo: WorkOrder) => void
}) {
  const toast = useToast()
  const done = useDone()
  const [vendor, setVendor] = React.useState('')
  const [projectId, setProjectId] = React.useState('')
  const [siteId, setSiteId] = React.useState('all')
  const [title, setTitle] = React.useState('')
  const [start, setStart] = React.useState('')
  const [end, setEnd] = React.useState('')
  const [retention, setRetention] = React.useState('5')
  const [defect, setDefect] = React.useState('')
  const [advance, setAdvance] = React.useState('')
  const [tds, setTds] = React.useState('')
  const [terms, setTerms] = React.useState('')
  const [lines, setLines] = React.useState<DraftLine[]>([])
  const [pickBoq, setPickBoq] = React.useState(false)

  const vendors = useQuery({ queryKey: ['vendors', 'all'], queryFn: fetchVendors, enabled: open })
  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, enabled: open, staleTime: 60_000 })
  const sites = useQuery({ queryKey: ['scope-sites', projectId], queryFn: () => fetchSites(projectId), enabled: open && !!projectId, staleTime: 60_000 })
  const boq = useQuery({ queryKey: ['boq', projectId], queryFn: () => fetchBoq(projectId), enabled: open && !!projectId, retry: false })

  React.useEffect(() => {
    if (!open) return
    const e = editing
    setVendor(e?.vendor_name ?? preset?.vendor_name ?? '')
    setProjectId(e?.project_id ?? preset?.project_id ?? '')
    setSiteId(e?.site_id ?? preset?.site_id ?? 'all')
    setTitle(e?.title ?? '')
    setStart(e?.start_date ?? today())
    setEnd(e?.end_date ?? '')
    setRetention(e?.retention_pct ? String(Number(e.retention_pct)) : '5')
    setDefect(e?.defect_days ? String(e.defect_days) : '')
    setAdvance(e?.advance_agreed ? String(Number(e.advance_agreed)) : '')
    setTds(e?.tds_pct ? String(Number(e.tds_pct)) : '')
    setTerms(e?.terms ?? '')
    setLines(e ? e.lines.map((l) => ({ key: l.id, id: l.id, planned_item_id: l.planned_item_id, description: l.description, unit: l.unit, quantity: l.quantity, rate: String(Number(l.rate ?? 0)) }))
      : [{ key: 'n0', description: '', unit: 'cum', quantity: '', rate: '' }])
    setPickBoq(false)
  }, [open, editing, preset])

  const subs = (vendors.data ?? []).filter((v) => v.status === 'active').sort((a, b) => Number(b.kind === 'subcontractor') - Number(a.kind === 'subcontractor') || a.name.localeCompare(b.name))
  const picked = subs.find((v) => v.name.toLowerCase() === vendor.trim().toLowerCase())
  const value = lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.rate) || 0), 0)
  const boqLines = (boq.data?.sections ?? []).flatMap((s) => s.lines.map((l) => ({ ...l, section: s.name })))
  const setLine = (key: string, patch: Partial<DraftLine>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const ready = lines.filter((l) => (l.description || l.planned_item_id) && Number(l.quantity) > 0 && Number(l.rate) >= 0 && l.rate !== '')

  const save = useMutation({
    mutationFn: (issue: boolean) => {
      const body = {
        project_id: projectId, site_id: siteId === 'all' ? null : siteId, title: title.trim() || null, start_date: start || null, end_date: end || null,
        retention_pct: retention || '0', defect_days: defect ? Number(defect) : 0, advance_agreed: advance || null, tds_pct: tds || null,
        terms: terms.trim() || null,
        lines: ready.map((l) => ({ id: l.id, planned_item_id: l.planned_item_id ?? null, description: l.description, unit: l.unit, quantity: String(l.quantity), rate: String(l.rate) })),
      }
      return editing ? editWorkOrder(editing.id, body) : createWorkOrder({ ...body, ...(picked ? { vendor_id: picked.id } : { vendor_name: vendor.trim() }), issue })
    },
    onSuccess: (wo) => {
      done()
      toast.success(editing ? `${wo.ref} saved` : `${wo.ref} ${wo.status === 'issued' ? 'issued' : 'saved as draft'}`, `${wo.vendor_name} · ${rupees(n(wo.totals.value))}`)
      onSaved?.(wo)
      onOpenChange(false)
    },
  })
  const canSave = !!projectId && (!!editing || !!vendor.trim()) && ready.length > 0 && !save.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit ${editing.ref}` : 'New work order'}</DialogTitle>
          <DialogDescription>{editing?.status === 'issued' ? 'It is issued: every change is kept in its history, and a line never goes below what is measured or billed.' : 'Work given to a subcontractor at an agreed rate, paid against what is measured.'}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Subcontractor" htmlFor="wo-vendor" hint={!editing && vendor.trim() && !picked ? `“${vendor.trim()}” will be added as a subcontractor.` : undefined}>
              <Input id="wo-vendor" list="wo-vendors" autoFocus={!editing} disabled={!!editing} value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="Ravi Concrete Team" />
              <datalist id="wo-vendors">{subs.map((v) => <option key={v.id} value={v.name}>{v.kind === 'subcontractor' ? 'Subcontractor' : ''}</option>)}</datalist>
            </Field>
            <Field label="What is the work" htmlFor="wo-title"><Input id="wo-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="First-floor slab concreting" /></Field>
            <Field label="Project">
              <Select value={projectId} onValueChange={(v) => { setProjectId(v); setSiteId('all') }} disabled={!!editing}>
                <SelectTrigger><SelectValue placeholder="Pick the project" /></SelectTrigger>
                <SelectContent>{(projects.data ?? []).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Site">
              <Select value={siteId} onValueChange={setSiteId} disabled={!projectId}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Whole project</SelectItem>
                  {(sites.data ?? []).map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
          </div>

          <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Work and agreed rates</h3>
              <div className="flex gap-1.5">
                {boqLines.length > 0 && <Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={() => setPickBoq((x) => !x)}><ListPlus className="size-4" /> From the BOQ</Button>}
                <Button type="button" size="sm" variant="outline" className="gap-1.5" onClick={() => setLines((ls) => [...ls, { key: `n${Date.now()}`, description: '', unit: 'cum', quantity: '', rate: '' }])}><Plus className="size-4" /> Line</Button>
              </div>
            </div>
            {pickBoq && (
              <ul className="max-h-48 divide-y overflow-y-auto rounded-lg border bg-muted/20 text-sm">
                {boqLines.map((b) => {
                  const on = lines.some((l) => l.planned_item_id === b.id)
                  return (
                    <li key={b.id}>
                      <button type="button" disabled={on} className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted disabled:opacity-50"
                        onClick={() => setLines((ls) => [...ls.filter((l) => l.description || l.planned_item_id), { key: b.id, planned_item_id: b.id, description: b.work, unit: b.unit, quantity: String(Number(b.planned_quantity)), rate: b.subcontract_rate ? String(Number(b.subcontract_rate)) : '' }])}>
                        <span className="w-14 shrink-0 text-xs text-muted-foreground">{b.boq_code}</span>
                        <span className="min-w-0 flex-1 truncate">{b.work} <span className="text-xs text-muted-foreground">· {b.section}</span></span>
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{Number(b.planned_quantity).toLocaleString('en-IN')} {b.unit}{b.subcontract_rate ? ` · ₹${Number(b.subcontract_rate)}` : ''}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            <div className="hidden grid-cols-[1fr_92px_100px_100px_110px_32px] gap-2 px-1 text-xs text-muted-foreground sm:grid">
              <span>Work</span><span>Unit</span><span>Quantity</span><span>Rate ₹</span><span className="text-right">Amount</span><span />
            </div>
            {lines.map((l) => (
              <div key={l.key} className="grid grid-cols-2 gap-2 rounded-lg border p-2 sm:grid-cols-[1fr_92px_100px_100px_110px_32px] sm:border-0 sm:p-0">
                <Input aria-label="Work" className="col-span-2 sm:col-span-1" value={l.description ?? ''} onChange={(e) => setLine(l.key, { description: e.target.value })} placeholder="Concreting M20" />
                <Select value={l.unit ?? 'cum'} onValueChange={(v) => setLine(l.key, { unit: v })}>
                  <SelectTrigger aria-label="Unit"><SelectValue /></SelectTrigger>
                  <SelectContent>{[...new Set([...(l.unit ? [l.unit] : []), ...UNITS])].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                </Select>
                <Input aria-label="Quantity" type="number" min={0} step="any" inputMode="decimal" value={l.quantity} onChange={(e) => setLine(l.key, { quantity: e.target.value })} placeholder="400" />
                <Input aria-label="Agreed rate" type="number" min={0} step="any" inputMode="decimal" value={l.rate} onChange={(e) => setLine(l.key, { rate: e.target.value })} placeholder="380" />
                <span className="self-center text-right text-sm font-medium tabular-nums">{rupees((Number(l.quantity) || 0) * (Number(l.rate) || 0))}</span>
                <Button type="button" size="icon" variant="ghost" className="size-8 self-center text-muted-foreground" aria-label="Remove line" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <div className="flex justify-end text-sm">Work order value <span className="ml-2 font-semibold tabular-nums">{rupees(value)}</span></div>
          </section>

          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="Start" htmlFor="wo-start"><Input id="wo-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="dark:[color-scheme:dark]" /></Field>
            <Field label="Finish by" htmlFor="wo-end"><Input id="wo-end" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} className="dark:[color-scheme:dark]" /></Field>
            <Field label="Retention %" htmlFor="wo-ret" hint="Held from each bill"><Input id="wo-ret" type="number" min={0} max={50} step="any" value={retention} onChange={(e) => setRetention(e.target.value)} /></Field>
            <Field label="Defect period (days)" htmlFor="wo-def" hint="Retention after this"><Input id="wo-def" type="number" min={0} value={defect} onChange={(e) => setDefect(e.target.value)} placeholder="0" /></Field>
            <Field label="Advance agreed ₹" htmlFor="wo-adv" hint={n(advance) && value ? `Recovered ${(n(advance) / value * 100).toFixed(1)}% from each bill` : 'Recovered from the bills'}><Input id="wo-adv" type="number" min={0} step="any" value={advance} onChange={(e) => setAdvance(e.target.value)} placeholder="0" /></Field>
            <Field label="TDS %" htmlFor="wo-tds" hint="Empty: the company's (194C)"><Input id="wo-tds" type="number" min={0} max={20} step="any" value={tds} onChange={(e) => setTds(e.target.value)} placeholder="1" /></Field>
            <Field label="Terms" htmlFor="wo-terms" className="sm:col-span-2"><Input id="wo-terms" value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="Shuttering material by us; curing by you" /></Field>
          </div>
          <Err error={save.error} />
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          {!editing && <Button variant="outline" disabled={!canSave} onClick={() => save.mutate(false)}>Save draft</Button>}
          <Button className="font-semibold" disabled={!canSave} onClick={() => save.mutate(true)}>{save.isPending ? 'Saving…' : editing ? 'Save' : 'Issue work order'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Measurement ---------------------------------------------------------------------------------------------------

export function MeasureDialog({ open, onOpenChange, wo, lineId }: { open: boolean; onOpenChange: (o: boolean) => void; wo: WorkOrder; lineId?: string }) {
  const toast = useToast()
  const done = useDone()
  const [line, setLine] = React.useState('')
  const [qty, setQty] = React.useState('')
  const [date, setDate] = React.useState(today())
  const [notes, setNotes] = React.useState('')
  React.useEffect(() => { if (open) { setLine(lineId ?? wo.lines[0]?.id ?? ''); setQty(''); setDate(today()); setNotes('') } }, [open, lineId, wo])
  const l = wo.lines.find((x) => x.id === line)
  const after = n(l?.measured) + (Number(qty) || 0)
  const save = useMutation({
    mutationFn: () => addMeasurement(wo.id, { line_id: line, quantity: qty, measured_on: date, notes: notes.trim() || undefined }),
    onSuccess: () => { done(); toast.success(`${qty} ${l?.unit} measured`, `${l?.description}: ${after.toLocaleString('en-IN')} of ${n(l?.quantity).toLocaleString('en-IN')} ${l?.unit} done`); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Measure work · {wo.ref}</DialogTitle><DialogDescription>{wo.vendor_name}: what was done, measured on site.</DialogDescription></DialogHeader>
        <form id="measure-form" className="grid gap-3" onSubmit={(e) => { e.preventDefault(); if (line && Number(qty) > 0) save.mutate() }}>
          <Field label="Work">
            <Select value={line} onValueChange={setLine}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{wo.lines.map((x) => <SelectItem key={x.id} value={x.id}>{x.description} · {Number(x.measured)}/{Number(x.quantity)} {x.unit}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={`Quantity (${l?.unit ?? ''})`} htmlFor="m-q"><Input id="m-q" autoFocus type="number" min={0} step="any" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
            <Field label="Measured on" htmlFor="m-d"><Input id="m-d" type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} className="dark:[color-scheme:dark]" /></Field>
          </div>
          {l && Number(qty) > 0 && (
            <p className={cn('text-sm', after > n(l.quantity) ? 'text-draft' : 'text-muted-foreground')}>
              {after > n(l.quantity) ? <AlertTriangle className="mr-1 inline size-4" /> : null}
              Then {after.toLocaleString('en-IN')} of {n(l.quantity).toLocaleString('en-IN')} {l.unit} done{after > n(l.quantity) ? `: ${(after - n(l.quantity)).toLocaleString('en-IN')} more than agreed (saved and flagged)` : ''}.
            </p>
          )}
          <Field label="Note" htmlFor="m-n"><Input id="m-n" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Grid A–C, first floor" /></Field>
          <Err error={save.error} />
        </form>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" form="measure-form" disabled={!line || !(Number(qty) > 0) || save.isPending}>{save.isPending ? 'Saving…' : 'Save measurement'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Bill ----------------------------------------------------------------------------------------------------------

export function BillDialog({ open, onOpenChange, wo }: { open: boolean; onOpenChange: (o: boolean) => void; wo: WorkOrder }) {
  const toast = useToast()
  const done = useDone()
  const [qty, setQty] = React.useState<Record<string, string>>({})
  const [rate, setRate] = React.useState<Record<string, string>>({})
  const [amount, setAmount] = React.useState('')
  const [no, setNo] = React.useState('')
  const [date, setDate] = React.useState(today())
  const [check, setCheck] = React.useState<BillCheck | null>(null)
  React.useEffect(() => {
    if (!open) return
    setQty(Object.fromEntries(wo.lines.filter((l) => n(l.to_bill) > 0).map((l) => [l.id, String(Number(l.to_bill))])))
    setRate(Object.fromEntries(wo.lines.map((l) => [l.id, String(Number(l.rate ?? 0))])))
    setAmount(''); setNo(''); setDate(today()); setCheck(null)
  }, [open, wo])
  const body = React.useMemo(() => ({
    lines: wo.lines.filter((l) => Number(qty[l.id]) > 0).map((l) => ({ line_id: l.id, quantity: qty[l.id], rate: rate[l.id] })),
    ...(amount ? { amount } : {}), their_bill_no: no || undefined, bill_date: date,
  }), [wo, qty, rate, amount, no, date])
  React.useEffect(() => {
    if (!open || !body.lines.length) { setCheck(null); return }
    const t = setTimeout(() => { checkBill(wo.id, body).then(setCheck).catch(() => setCheck(null)) }, 350)
    return () => clearTimeout(t)
  }, [open, wo.id, body])
  const save = useMutation({
    mutationFn: () => recordBill(wo.id, body),
    onSuccess: (r) => {
      done()
      toast.success(`${r.bill.ref} recorded`, r.bill.check_status === 'passed' ? `Passed the check: ${rupees(n(r.bill.payable_now))} payable now.` : 'Flagged: it waits for approval before it can be paid.')
      onOpenChange(false)
    },
  })
  const d = check?.deductions
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader><DialogTitle>Bill from {wo.vendor_name} · {wo.ref}</DialogTitle><DialogDescription>Each line is checked against what was measured and the agreed rate before it can be paid.</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <div className="hidden grid-cols-[1fr_120px_100px_100px] gap-2 px-1 text-xs text-muted-foreground sm:grid"><span>Work</span><span>Measured / billed</span><span>Billed now</span><span>Rate ₹</span></div>
          {wo.lines.map((l) => (
            <div key={l.id} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[1fr_120px_100px_100px]">
              <span className="col-span-2 truncate text-sm font-medium sm:col-span-1">{l.description}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{Number(l.measured)} / {Number(l.billed)} {l.unit}</span>
              <Input aria-label={`Billed now for ${l.description}`} type="number" min={0} step="any" inputMode="decimal" value={qty[l.id] ?? ''} onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))} placeholder="0" />
              <Input aria-label={`Rate for ${l.description}`} type="number" min={0} step="any" inputMode="decimal" value={rate[l.id] ?? ''} onChange={(e) => setRate((r) => ({ ...r, [l.id]: e.target.value }))}
                className={cn(Number(rate[l.id]) > n(l.rate) && 'border-destructive')} />
            </div>
          ))}
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Their bill no." htmlFor="b-no"><Input id="b-no" value={no} onChange={(e) => setNo(e.target.value)} placeholder="RC/7" /></Field>
            <Field label="Bill date" htmlFor="b-d"><Input id="b-d" type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} className="dark:[color-scheme:dark]" /></Field>
            <Field label="Bill total ₹" htmlFor="b-a" hint="Empty: the lines' total"><Input id="b-a" type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={check?.gross} /></Field>
          </div>
          {check && (
            <div className={cn('grid gap-2 rounded-lg border p-3 text-sm', check.flags.length ? 'border-destructive/40 bg-destructive/5' : 'border-success/30 bg-success-soft')} aria-live="polite">
              <div className="flex items-center gap-2 font-semibold">
                {check.flags.length ? <AlertTriangle className="size-4 text-destructive" /> : <CircleCheck className="size-4 text-success" />}
                {check.flags.length ? 'Flagged: waits for approval' : 'Passes the check'}
              </div>
              {check.flags.map((f, i) => <div key={i} className="text-destructive">• {f.words}</div>)}
              {d && (
                <dl className="grid grid-cols-2 gap-x-6 gap-y-0.5 sm:grid-cols-5">
                  <div><dt className="text-xs text-muted-foreground">Bill</dt><dd className="font-semibold tabular-nums">{rupees(n(d.gross))}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Retention {Number(wo.retention_pct)}%</dt><dd className="tabular-nums">−{rupees(n(d.retention))}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Advance back</dt><dd className="tabular-nums">−{rupees(n(d.advance))}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">TDS{check.tds_pct ? ` ${Number(check.tds_pct)}%` : ' (off)'}</dt><dd className="tabular-nums">−{rupees(n(d.tds))}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Payable</dt><dd className="font-semibold tabular-nums">{rupees(n(d.net))}</dd></div>
                </dl>
              )}
            </div>
          )}
          <Err error={save.error} />
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button className="font-semibold" disabled={!body.lines.length || save.isPending} onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : check?.flags.length ? 'Record (flagged)' : 'Record bill'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Approve / reject ----------------------------------------------------------------------------------------------

export function DecideDialog({ bill, decision, onOpenChange }: { bill: WoBill | null; decision: 'approve' | 'reject'; onOpenChange: (o: boolean) => void }) {
  const toast = useToast()
  const done = useDone()
  const [reason, setReason] = React.useState('')
  React.useEffect(() => setReason(''), [bill])
  const save = useMutation({
    mutationFn: () => decideBill(bill!.id, decision, reason.trim()),
    onSuccess: () => { done(); toast.success(`${bill!.ref} ${decision === 'approve' ? 'approved' : 'rejected'}`); onOpenChange(false) },
  })
  return (
    <Dialog open={!!bill} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{decision === 'approve' ? 'Approve' : 'Reject'} {bill?.ref} · {rupees(n(bill?.gross))}</DialogTitle>
          <DialogDescription>{decision === 'approve' ? 'It becomes payable after retention, advance and TDS. Say why it is fine despite the check.' : 'The bill is taken back: nothing is owed for it. Say why, for the subcontractor.'}</DialogDescription>
        </DialogHeader>
        {bill?.flags.length ? <ul className="rounded-lg bg-muted/40 p-3 text-sm">{bill.flags.map((f, i) => <li key={i}>• {f.words}</li>)}</ul> : null}
        <Field label="Reason" htmlFor="d-r"><Input id="d-r" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder={decision === 'approve' ? 'Measured late; checked on site today' : 'Only 200 sqm done'} /></Field>
        <Err error={save.error} />
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={decision === 'reject' ? 'destructive' : 'default'} disabled={reason.trim().length < 2 || save.isPending} onClick={() => save.mutate()}>{decision === 'approve' ? 'Approve' : 'Reject'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --- Advance, retention ------------------------------------------------------------------------------------------

export function AdvanceDialog({ open, onOpenChange, wo }: { open: boolean; onOpenChange: (o: boolean) => void; wo: WorkOrder }) {
  const toast = useToast()
  const done = useDone()
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'payable'], queryFn: () => fetchAccountsApi(), enabled: open })
  const active = ((accounts.data ?? []) as { id: string; name: string; account_type: string; current_balance: string; status?: string }[]).filter((a) => a.status !== 'inactive' && !a.name.startsWith('TDS payable'))
  const [account, setAccount] = React.useState('')
  const [amount, setAmount] = React.useState('')
  const [method, setMethod] = React.useState('Bank transfer')
  const [ref, setRef] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setAmount(String(Math.max(0, n(wo.advance_agreed) - n(wo.totals.advance_given)) || ''))
    setRef('')
  }, [open, wo])
  React.useEffect(() => { if (!account && active.length) setAccount(String((active.find((a) => a.account_type === 'bank') ?? active[0]).id)) }, [active, account])
  const save = useMutation({
    mutationFn: () => giveAdvance(wo.id, { account_id: account, amount, method, reference: ref || undefined }),
    onSuccess: () => { done(); toast.success(`Advance ${rupees(Number(amount))} to ${wo.vendor_name}`, 'Recovered from the work order’s bills.'); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Advance · {wo.ref}</DialogTitle><DialogDescription>{wo.advance_agreed ? `Agreed ${rupees(n(wo.advance_agreed))}; given ${rupees(n(wo.totals.advance_given))}.` : 'Money given before the work; it comes back from each bill.'}</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label="Amount ₹" htmlFor="a-a"><Input id="a-a" autoFocus type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Field label="From">
            <Select value={account} onValueChange={setAccount}>
              <SelectTrigger><SelectValue placeholder="Which account" /></SelectTrigger>
              <SelectContent>{active.map((a) => <SelectItem key={a.id} value={String(a.id)}>{a.name} · {rupees(Number(a.current_balance) || 0)}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="How"><Select value={method} onValueChange={setMethod}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{PAY_METHODS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Reference" htmlFor="a-r"><Input id="a-r" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR" /></Field>
          </div>
          <Err error={save.error} />
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!account || !(Number(amount) > 0) || save.isPending} onClick={() => save.mutate()}>Give advance</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ReleaseDialog({ open, onOpenChange, wo }: { open: boolean; onOpenChange: (o: boolean) => void; wo: WorkOrder }) {
  const toast = useToast()
  const done = useDone()
  const held = n(wo.totals.retention_held)
  const [amount, setAmount] = React.useState('')
  const [note, setNote] = React.useState('')
  React.useEffect(() => { if (open) { setAmount(String(held)); setNote('') } }, [open, held])
  const dueOn = wo.completed_on ? new Date(new Date(`${wo.completed_on}T00:00:00`).getTime() + wo.defect_days * 86400000) : null
  const early = dueOn && dueOn > new Date()
  const save = useMutation({
    mutationFn: () => releaseRetention(wo.id, { amount, note: note || undefined }),
    onSuccess: () => { done(); toast.success(`${rupees(Number(amount))} retention released`, 'It can be paid now (Pay on the subcontractor).'); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Release retention · {wo.ref}</DialogTitle><DialogDescription>{rupees(held)} held from {wo.vendor_name}’s bills.</DialogDescription></DialogHeader>
        {early && <p className="rounded-md bg-draft-soft px-3 py-2 text-sm text-draft">The defect period ends on {dueOn!.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}.</p>}
        {!wo.completed_on && <p className="rounded-md bg-draft-soft px-3 py-2 text-sm text-draft">The work is not marked done yet.</p>}
        <div className="grid gap-3">
          <Field label="Amount ₹" htmlFor="r-a"><Input id="r-a" type="number" min={0} max={held} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
          <Field label="Note" htmlFor="r-n"><Input id="r-n" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Defects checked with the client" /></Field>
          <Err error={save.error} />
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!(Number(amount) > 0) || Number(amount) > held || save.isPending} onClick={() => save.mutate()}>Release</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
