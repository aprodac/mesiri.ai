import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, ClipboardCheck, FileText, Handshake, MessageCircle, Printer, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { VendorTile } from '@/components/orders/order-detail'
import { DecideDialog } from '@/components/subcontracts/dialogs'
import { Progress3 } from '@/components/subcontracts/parts'
import { ValueStrip } from '@/components/subcontracts/value-strip'
import { useAuth } from '@/lib/AuthContext'
import { useReadOnly } from '@/lib/trial'
import { usePageTitle } from '@/lib/page-title'
import { rupees } from '@/lib/expenses'
import { day, fetchPayables, vendorUrl } from '@/lib/vendors'
import { cn } from '@/lib/utils'
import { ModuleTitle } from '@/components/page/page-kit'
import { useScope } from '@/lib/ScopeContext'
import {
  CHECK_LOOK, WO_LOOK, fetchBillsWaiting, fetchStatement, fetchWorkOrder, fetchWorkOrders, n, statementText, waLink, woUrl, workOrderText,
  type WoBill,
} from '@/lib/subcontracts'

// NXT-06/07, NXT-17 (8 Nov 2026): the other subcontract pages. Bills & checks (every bill waiting for a person, with why,
// approve / reject); Subcontractors (each team: work orders, done, billed, payable, retention, advance; their statement);
// a subcontractor's statement (print, send on WhatsApp); the work order document (print, send).

// --- Bills & checks ------------------------------------------------------------------------------------------------

export function BillsChecksPage() {
  usePageTitle('Bills & checks')
  const readOnly = useReadOnly()
  const navigate = useNavigate()
  const waiting = useQuery({ queryKey: ['subcontracts', 'waiting'], queryFn: fetchBillsWaiting })
  const [deciding, setDeciding] = React.useState<{ bill: WoBill; decision: 'approve' | 'reject' } | null>(null)
  // SCP-03: with a project or a site picked, its bills only.
  const { scope } = useScope()
  const list = (waiting.data ?? []).filter(
    (b) => scope.mode === 'portfolio' || (b.project_id === scope.projectId && (scope.mode !== 'site' || b.site_id === scope.siteId)),
  )
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center gap-3">
        <ModuleTitle icon={ClipboardCheck} title="Bills & checks" />
      </header>
      <ValueStrip />
      <p className="text-sm text-muted-foreground">A subcontractor’s bill is checked against the work measured and the agreed rates. These did not pass, or were sent by the subcontractor: each waits for a person before anything is paid.</p>
      {waiting.isError ? <Callout tone="draft" icon={TriangleAlert}>The bills could not be loaded.</Callout>
        : waiting.isLoading ? <Skeleton className="h-40 rounded-xl" />
        : !list.length ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center text-sm"><Check className="size-6 text-success" /><span className="font-medium">Nothing waiting</span><span className="text-muted-foreground">Every subcontract bill passed its check or was decided.</span></div>
        ) : (
          <ul className="grid gap-2">
            {list.map((b) => (
              <li key={b.id} className="rounded-xl border bg-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <VendorTile id={b.vendor_id} name={b.vendor_name ?? ''} />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{b.vendor_name} · {b.ref} <Link to={woUrl(b.work_order_id, 'bills')} className="text-sm font-normal text-muted-foreground underline-offset-2 hover:underline">{b.wo_ref}</Link></span>
                    <span className="block text-xs text-muted-foreground">{[b.project_name, b.site_name].filter(Boolean).join(' › ')} · {day(b.bill_date)}{b.submitted_by_contact ? ' · sent by the subcontractor' : b.submitted_by_name ? ` · by ${b.submitted_by_name}` : ''}</span>
                  </span>
                  <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', CHECK_LOOK[b.check_status].chip)}>{CHECK_LOOK[b.check_status].label}</span>
                  <span className="text-lg font-semibold tabular-nums">{rupees(n(b.gross))}</span>
                </div>
                {n(b.caught) > 0 && <div className="mt-1 text-sm font-semibold text-destructive">{rupees(n(b.caught))} of it is for work not measured or above the agreed rate</div>}
                {b.flags.length > 0 && <ul className="mt-2 grid gap-0.5 text-sm text-destructive">{b.flags.map((f, i) => <li key={i}>⚠ {f.words}</li>)}</ul>}
                <div className="mt-2 flex flex-wrap gap-2">
                  {!readOnly && <Button size="sm" className="gap-1" onClick={() => setDeciding({ bill: b, decision: 'approve' })}><Check className="size-4" /> Approve</Button>}
                  {!readOnly && <Button size="sm" variant="outline" onClick={() => setDeciding({ bill: b, decision: 'reject' })}>Reject</Button>}
                  <Button size="sm" variant="ghost" onClick={() => navigate(woUrl(b.work_order_id, 'bills'))}>Open work order</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      {deciding && <DecideDialog bill={deciding.bill} decision={deciding.decision} onOpenChange={(o) => !o && setDeciding(null)} />}
    </div>
  )
}

// --- Subcontractors ------------------------------------------------------------------------------------------------

export function SubcontractorsPage() {
  usePageTitle('Subcontractors')
  const navigate = useNavigate()
  // SCP-03: with a project picked, the subcontractors working on it and their figures there.
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? '' : scope.projectId
  const wos = useQuery({ queryKey: ['subcontracts', 'list', projectId], queryFn: () => fetchWorkOrders(projectId ? { project_id: projectId } : {}) })
  const pay = useQuery({ queryKey: ['finance', 'payables', 'sub', projectId], queryFn: () => fetchPayables({ include_settled: true, ...(projectId ? { project_id: projectId } : {}) }), retry: false })
  const money = !!wos.data?.with_money
  const teams = React.useMemo(() => {
    const by = new Map<string, { id: string; name: string; open: number; value: number; done: number; billed: number; payable: number; held: number; advance: number; check: number; sites: Set<string> }>()
    for (const w of wos.data?.work_orders ?? []) {
      if (w.status === 'cancelled') continue
      const t = by.get(w.vendor_id) ?? { id: w.vendor_id, name: w.vendor_name, open: 0, value: 0, done: 0, billed: 0, payable: 0, held: 0, advance: 0, check: 0, sites: new Set<string>() }
      t.open += w.status === 'issued' ? 1 : 0
      t.value += n(w.totals.value); t.done += n(w.totals.measured_value); t.billed += n(w.totals.billed)
      t.payable += n(w.totals.payable_now); t.held += n(w.totals.retention_held); t.advance += n(w.totals.advance_left); t.check += w.totals.to_check
      t.sites.add(w.site_name ?? w.project_name)
      by.set(w.vendor_id, t)
    }
    for (const v of pay.data?.vendors ?? []) if (v.kind === 'subcontractor' && !by.has(v.id)) by.set(v.id, { id: v.id, name: v.name, open: 0, value: 0, done: 0, billed: 0, payable: 0, held: 0, advance: 0, check: 0, sites: new Set() })
    return [...by.values()].sort((a, b) => b.open - a.open || b.value - a.value)
  }, [wos.data, pay.data])
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <ModuleTitle icon={Handshake} title="Subcontractors" />
        </div>
        <Button variant="outline" onClick={() => navigate('/subcontract/work-orders')}>Work orders</Button>
      </header>
      {wos.isLoading ? <Skeleton className="h-48 rounded-xl" /> : !teams.length ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground"><Handshake className="size-6" />No subcontractor yet: a work order adds one.</div>
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {teams.map((t) => (
            <li key={t.id} className="rounded-xl border bg-card p-3">
              <div className="flex items-center gap-3">
                <VendorTile id={t.id} name={t.name} />
                <span className="min-w-0 flex-1">
                  <Link to={vendorUrl(t.id)} className="block truncate font-semibold hover:underline">{t.name}</Link>
                  <span className="block truncate text-xs text-muted-foreground">{t.open} open work {t.open === 1 ? 'order' : 'orders'}{t.sites.size ? ` · ${[...t.sites].join(', ')}` : ''}</span>
                </span>
                {t.check > 0 && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-100">{t.check} to check</span>}
              </div>
              {t.value > 0 && <Progress3 className="mt-3" done={Math.round(t.done / t.value * 100)} billed={money ? Math.round(t.billed / t.value * 100) : undefined} />}
              {money && (
                <dl className="mt-2 grid grid-cols-4 gap-2 text-xs">
                  <div><dt className="text-muted-foreground">Work</dt><dd className="font-medium tabular-nums">{rupees(t.value)}</dd></div>
                  <div><dt className="text-muted-foreground">Payable now</dt><dd className="font-medium tabular-nums">{rupees(t.payable)}</dd></div>
                  <div><dt className="text-muted-foreground">Retention</dt><dd className="font-medium tabular-nums">{rupees(t.held)}</dd></div>
                  <div><dt className="text-muted-foreground">Advance left</dt><dd className="font-medium tabular-nums">{rupees(t.advance)}</dd></div>
                </dl>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => navigate(`/subcontract/work-orders?vendor=${t.id}&tab=all`)}>Work orders</Button>
                {money && <Button size="sm" variant="outline" className="gap-1" onClick={() => navigate(`/subcontract/statement/${t.id}`)}><FileText className="size-4" /> Statement</Button>}
                <Button size="sm" variant="ghost" onClick={() => navigate(vendorUrl(t.id))}>Account</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// --- Statement -----------------------------------------------------------------------------------------------------

export function StatementPage() {
  const { vendorId = '' } = useParams()
  const { me } = useAuth()
  const q = useQuery({ queryKey: ['subcontracts', 'statement', vendorId], queryFn: () => fetchStatement(vendorId), enabled: !!vendorId })
  usePageTitle(q.data ? `Statement · ${q.data.vendor.name}` : 'Statement')
  if (q.isError) return <div className="mx-auto max-w-3xl py-12"><Callout tone="draft" icon={TriangleAlert}>The statement could not be loaded.</Callout></div>
  if (!q.data) return <Skeleton className="mx-auto h-96 max-w-4xl rounded-xl" />
  const s = q.data
  const t = s.totals
  const company = me?.organization_name ?? 'Mesiri'
  return (
    <div className="min-h-screen bg-muted/40 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] flex-wrap items-center justify-between gap-2 px-4 print:hidden">
        <Link to={vendorUrl(s.vendor.id)} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {s.vendor.name}</Link>
        <div className="flex gap-2">
          <Button variant="outline" className="gap-1.5" asChild><a href={waLink(s.vendor.phone, statementText(s, company))} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send on WhatsApp</a></Button>
          <Button className="gap-1.5" onClick={() => window.print()}><Printer className="size-4" /> Print / PDF</Button>
        </div>
      </div>
      <article className="mx-auto max-w-[210mm] bg-white px-10 py-9 text-[13px] text-neutral-900 shadow-sm print:max-w-none print:px-0 print:py-0 print:shadow-none">
        <header className="flex justify-between border-b pb-3">
          <div><div className="text-lg font-bold">{company}</div><div className="text-neutral-600">Subcontractor statement</div></div>
          <div className="text-right"><div className="font-semibold">{s.vendor.name}</div>{s.vendor.gstin && <div>GSTIN {s.vendor.gstin}</div>}<div>As of {day(s.as_of)}</div></div>
        </header>
        <table className="mt-4 w-full">
          <tbody>
            {[['Work orders', t.value], ['Work done (measured)', t.measured_value], ['Billed', t.billed], ['Approved', t.approved], ['Paid', t.paid], ['TDS deducted', t.tds], ['Advance given', t.advance_given], ['Advance recovered', t.advance_recovered], ['Retention held', t.retention_held]].map(([k, v]) => (
              <tr key={k} className="border-b border-neutral-200"><td className="py-1">{k}</td><td className="py-1 text-right tabular-nums">{rupees(n(v))}</td></tr>
            ))}
            <tr className="font-bold"><td className="py-2">Payable now</td><td className="py-2 text-right tabular-nums">{rupees(n(t.payable_now))}</td></tr>
          </tbody>
        </table>
        {s.work_orders.map((w) => (
          <section key={w.id} className="mt-5 break-inside-avoid">
            <h2 className="font-semibold">{w.ref} · {w.title ?? ''} <span className="font-normal text-neutral-600">({WO_LOOK[w.status].label}; {[w.project_name, w.site_name].filter(Boolean).join(' › ')})</span></h2>
            <table className="mt-1 w-full">
              <thead><tr className="border-b text-left text-neutral-600"><th className="py-1 font-medium">Work</th><th className="text-right font-medium">Agreed</th><th className="text-right font-medium">Rate</th><th className="text-right font-medium">Done</th><th className="text-right font-medium">Billed</th></tr></thead>
              <tbody>{w.lines.map((l) => <tr key={l.id} className="border-b border-neutral-100"><td className="py-1">{l.description}</td><td className="text-right tabular-nums">{l.quantity} {l.unit}</td><td className="text-right tabular-nums">₹{Number(l.rate)}</td><td className="text-right tabular-nums">{l.measured}</td><td className="text-right tabular-nums">{l.billed}</td></tr>)}</tbody>
            </table>
            {w.bills.filter((b) => b.check_status !== 'rejected').length > 0 && (
              <table className="mt-2 w-full">
                <thead><tr className="border-b text-left text-neutral-600"><th className="py-1 font-medium">Bill</th><th className="font-medium">Date</th><th className="text-right font-medium">Amount</th><th className="text-right font-medium">Retention</th><th className="text-right font-medium">Advance</th><th className="text-right font-medium">TDS</th><th className="text-right font-medium">Paid</th><th className="text-right font-medium">Status</th></tr></thead>
                <tbody>{w.bills.filter((b) => b.check_status !== 'rejected').map((b) => (
                  <tr key={b.id} className="border-b border-neutral-100"><td className="py-1">{b.ref}{b.their_bill_no ? ` (${b.their_bill_no})` : ''}</td><td>{day(b.bill_date)}</td><td className="text-right tabular-nums">{rupees(n(b.gross))}</td><td className="text-right tabular-nums">{rupees(n(b.retention_amount))}</td><td className="text-right tabular-nums">{rupees(n(b.advance_recovered))}</td><td className="text-right tabular-nums">{rupees(n(b.tds_amount))}</td><td className="text-right tabular-nums">{rupees(n(b.paid_cash))}</td><td className="text-right">{CHECK_LOOK[b.check_status].label}</td></tr>
                ))}</tbody>
              </table>
            )}
          </section>
        ))}
      </article>
    </div>
  )
}

// --- Work order document -------------------------------------------------------------------------------------------

export function WorkOrderDocumentPage() {
  const { id = '' } = useParams()
  const { me } = useAuth()
  const q = useQuery({ queryKey: ['subcontracts', 'one', id], queryFn: () => fetchWorkOrder(id), enabled: !!id })
  usePageTitle(q.data ? `${q.data.ref} document` : 'Work order')
  if (!q.data) return <Skeleton className="mx-auto mt-6 h-96 max-w-4xl rounded-xl" />
  const wo = q.data
  const company = me?.organization_name ?? 'Mesiri'
  return (
    <div className="min-h-screen bg-muted/40 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-[210mm] flex-wrap items-center justify-between gap-2 px-4 print:hidden">
        <Link to={woUrl(wo.id)} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> {wo.ref}</Link>
        <div className="flex gap-2">
          <Button variant="outline" className="gap-1.5" asChild><a href={waLink(wo.vendor_phone, workOrderText(wo, company))} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send on WhatsApp</a></Button>
          <Button className="gap-1.5" onClick={() => window.print()}><Printer className="size-4" /> Print / PDF</Button>
        </div>
      </div>
      <article className="mx-auto max-w-[210mm] bg-white px-10 py-9 text-[13px] text-neutral-900 shadow-sm print:max-w-none print:px-0 print:py-0 print:shadow-none">
        <header className="flex justify-between border-b pb-3">
          <div><div className="text-lg font-bold">{company}</div><div className="text-neutral-600">Work order</div></div>
          <div className="text-right"><div className="text-lg font-bold">{wo.ref}</div><div>{day(wo.issued_at?.slice(0, 10) ?? wo.created_at.slice(0, 10))}</div>{wo.status === 'draft' && <div className="font-semibold text-orange-700">DRAFT</div>}</div>
        </header>
        <div className="mt-3 grid grid-cols-2 gap-4">
          <div><div className="text-neutral-600">To</div><div className="font-semibold">{wo.vendor_name}</div>{wo.vendor_phone && <div>{wo.vendor_phone}</div>}{wo.vendor_gstin && <div>GSTIN {wo.vendor_gstin}</div>}</div>
          <div><div className="text-neutral-600">Work at</div><div className="font-semibold">{wo.project_name}{wo.site_name ? ` › ${wo.site_name}` : ''}</div>{wo.start_date && <div>From {day(wo.start_date)}{wo.end_date ? ` to ${day(wo.end_date)}` : ''}</div>}</div>
        </div>
        {wo.title && <p className="mt-3 font-semibold">{wo.title}</p>}
        <table className="mt-3 w-full">
          <thead><tr className="border-b text-left text-neutral-600"><th className="py-1 font-medium">#</th><th className="font-medium">Work</th><th className="text-right font-medium">Quantity</th><th className="text-right font-medium">Rate</th><th className="text-right font-medium">Amount</th></tr></thead>
          <tbody>{wo.lines.map((l, i) => <tr key={l.id} className="border-b border-neutral-100"><td className="py-1">{i + 1}</td><td>{l.boq_code ? `${l.boq_code} ` : ''}{l.description}</td><td className="text-right tabular-nums">{Number(l.quantity).toLocaleString('en-IN')} {l.unit}</td><td className="text-right tabular-nums">{l.rate ? `₹${Number(l.rate).toLocaleString('en-IN')}` : ''}</td><td className="text-right tabular-nums">{l.amount ? rupees(n(l.amount)) : ''}</td></tr>)}</tbody>
          {wo.totals.value && <tfoot><tr className="font-bold"><td colSpan={4} className="py-2 text-right">Total</td><td className="text-right tabular-nums">{rupees(n(wo.totals.value))}</td></tr></tfoot>}
        </table>
        <ul className="mt-4 list-disc space-y-1 pl-5">
          <li>Payment against work measured on site, at the rates above.</li>
          {wo.retention_pct && Number(wo.retention_pct) > 0 && <li>Retention of {Number(wo.retention_pct)}% of each bill, released after completion{wo.defect_days ? ` and a defect period of ${wo.defect_days} days` : ''}.</li>}
          {wo.advance_agreed && Number(wo.advance_agreed) > 0 && <li>Advance of {rupees(n(wo.advance_agreed))}, recovered from the bills.</li>}
          {wo.tds_pct && <li>TDS at {Number(wo.tds_pct)}% (section 194C) deducted from each bill.</li>}
          {wo.terms && <li>{wo.terms}</li>}
        </ul>
        <div className="mt-12 grid grid-cols-2 gap-8 text-neutral-600"><div className="border-t pt-1">For {company}</div><div className="border-t pt-1">Accepted by {wo.vendor_name}</div></div>
      </article>
    </div>
  )
}
