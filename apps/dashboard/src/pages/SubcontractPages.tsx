import * as React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Check, ClipboardCheck, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Callout } from '@/components/dpr-page'
import { DecideDialog } from '@/components/subcontracts/dialogs'
import { SubcontractHeader, TradeTile } from '@/components/subcontracts/look'
import { ValueStrip } from '@/components/subcontracts/value-strip'
import { useAuth } from '@/lib/AuthContext'
import { useReadOnly } from '@/lib/trial'
import { usePageTitle } from '@/lib/page-title'
import { rupees } from '@/lib/expenses'
import { day, vendorUrl } from '@/lib/vendors'
import { useUrlState } from '@/lib/url-state'
import { jobTrade, tradeLook } from '@/lib/subcontract-look'
import { cn } from '@/lib/utils'
import { EmptyState, Segmented } from '@/components/page/page-kit'
import { useScope } from '@/lib/ScopeContext'
import {
  CHECK_LOOK, WO_LOOK, fetchBillsWaiting, fetchStatement, fetchWorkOrder, fetchWorkOrders, n, statementText, waLink, woUrl, workOrderText,
  type WoBill, type WorkOrder,
} from '@/lib/subcontracts'
import { ActionIcon } from '@/components/page/action-button'
import { Pager } from '@/components/page/pager'
import { usePagedUrl } from '@/lib/paging'

// NXT-06/07, NXT-17 (8 Nov 2026): the other subcontract pages. Bills & checks (every bill waiting for a person, each line
// drawn against what was measured and agreed (UX-64), approve / reject; and the bills already checked); the subcontractors
// page is SubcontractorsPage.tsx;
// a subcontractor's statement (print, send on WhatsApp); the work order document (print, send).

// --- Bills & checks ------------------------------------------------------------------------------------------------

type BillTab = 'waiting' | 'checked'

export function BillsChecksPage() {
  usePageTitle('Bills & checks')
  const readOnly = useReadOnly()
  const [tab, setTab] = useUrlState<BillTab>('tab', 'waiting')
  const waiting = useQuery({ queryKey: ['subcontracts', 'waiting'], queryFn: fetchBillsWaiting })
  const [deciding, setDeciding] = React.useState<{ bill: WoBill; decision: 'approve' | 'reject' } | null>(null)
  // SCP-03: with a project or a site picked, its bills only.
  const { scope } = useScope()
  const projectId = scope.mode === 'portfolio' ? '' : scope.projectId
  // UX-64: the work orders, for each bill line's measured quantity and agreed rate, and the bills already checked.
  const wos = useQuery({ queryKey: ['subcontracts', 'list', projectId], queryFn: () => fetchWorkOrders(projectId ? { project_id: projectId } : {}) })
  const inScope = (b: { project_id?: string; site_id?: string | null }) =>
    scope.mode === 'portfolio' || (b.project_id === scope.projectId && (scope.mode !== 'site' || b.site_id === scope.siteId))
  const list = (waiting.data ?? []).filter(inScope)
  const byWo = new Map((wos.data?.work_orders ?? []).map((w) => [w.id, w]))
  const checked = (wos.data?.work_orders ?? [])
    .filter((w) => scope.mode !== 'site' || w.site_id === scope.siteId)
    .flatMap((w) => (w.bills ?? []).filter((b) => b.check_status !== 'waiting' && b.check_status !== 'flagged').map((b) => ({ b, w })))
    .sort((x, y) => (y.b.decided_at ?? y.b.bill_date).localeCompare(x.b.decided_at ?? x.b.bill_date))
  // UX-37: numbered pages, kept in the address.
  const pagedList = usePagedUrl(list)
  const pagedChecked = usePagedUrl(checked)
  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <SubcontractHeader icon={ClipboardCheck} title="Bills & checks" />
      <ValueStrip projectId={projectId || undefined} />
      <Segmented label="Bills" value={tab} onChange={setTab} guide="bills.tabs" options={[{ value: 'waiting', label: 'Waiting', count: list.length }, { value: 'checked', label: 'Checked', count: checked.length }]} />
      {tab === 'waiting' && (waiting.isError ? <Callout tone="draft" icon={TriangleAlert}>The bills could not be loaded.</Callout>
        : waiting.isLoading ? <Skeleton className="h-40 rounded-xl" />
        : !list.length ? (
          <div data-guide="bills.empty"><EmptyState icon={Check} title="Nothing waiting" className="bg-card" /></div>
        ) : (
          <>
          <ul className="grid gap-3" data-guide="bills.list">
            {pagedList.shown.map((b) => {
              const wo = byWo.get(b.work_order_id)
              const look = wo ? jobTrade(wo) : tradeLook(`${b.vendor_name ?? ''} ${b.lines.map((l) => l.description).join(' ')}`)
              return (
                <li key={b.id} className={cn('relative overflow-hidden rounded-xl border bg-card p-4 shadow-xs before:absolute before:inset-y-0 before:left-0 before:w-1', b.check_status === 'flagged' ? 'before:bg-red-500' : 'before:bg-amber-500')}>
                  <div className="flex flex-wrap items-start gap-3">
                    <TradeTile look={look} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-semibold">{b.vendor_name}</span>
                        <span className="text-sm text-muted-foreground">{b.ref}{b.their_bill_no ? ` · their ${b.their_bill_no}` : ''}</span>
                        <Link to={woUrl(b.work_order_id, 'bills')} className="text-sm text-muted-foreground underline-offset-2 hover:underline">{b.wo_ref}</Link>
                      </span>
                      <span className="block text-xs text-muted-foreground">{[b.project_name, b.site_name].filter(Boolean).join(' › ')} · {day(b.bill_date)}{b.submitted_by_contact ? ' · sent by the subcontractor' : b.submitted_by_name ? ` · by ${b.submitted_by_name}` : ''}</span>
                    </span>
                    <span className="flex flex-col items-end gap-1">
                      <span className="text-xl font-semibold tabular-nums">{rupees(n(b.gross))}</span>
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', CHECK_LOOK[b.check_status].chip)}>{CHECK_LOOK[b.check_status].label}</span>
                    </span>
                  </div>
                  <BillLines bill={b} wo={wo} />
                  {n(b.caught) > 0 && <div className="mt-3 inline-flex rounded-lg bg-red-50 px-2.5 py-1 text-sm font-semibold text-red-800 dark:bg-red-950/50 dark:text-red-200">{rupees(n(b.caught))} above what was measured or agreed</div>}
                  <div className="mt-3 flex flex-wrap gap-2" data-guide="bills.decide">
                    {!readOnly && <Button size="sm" className="h-9 gap-1 sm:h-8" onClick={() => setDeciding({ bill: b, decision: 'approve' })}><Check className="size-4" /> Approve</Button>}
                    {!readOnly && <Button size="sm" variant="outline" className="h-9 text-destructive sm:h-8" onClick={() => setDeciding({ bill: b, decision: 'reject' })}>Reject</Button>}
                    <Button size="sm" variant="ghost" className="h-9 sm:h-8" asChild><Link to={woUrl(b.work_order_id, 'bills')}>Open work order</Link></Button>
                  </div>
                </li>
              )
            })}
          </ul>
            <Pager {...pagedList.pager} noun="bills" className="mt-2" />
          </>
        ))}
      {tab === 'checked' && (wos.isLoading ? <Skeleton className="h-40 rounded-xl" /> : !checked.length ? (
        <EmptyState icon={ClipboardCheck} title="No bill checked yet" className="bg-card" />
      ) : (
        <>
          <ul className="divide-y rounded-xl border bg-card shadow-xs" data-guide="bills.checked">
            {pagedChecked.shown.map(({ b, w }) => (
              <li key={b.id} className={cn('flex flex-wrap items-center gap-3 px-4 py-3', b.check_status === 'rejected' && 'opacity-70')}>
                <TradeTile look={jobTrade(w)} size="sm" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{w.vendor_name} · {b.ref} <Link to={woUrl(w.id, 'bills')} className="font-normal text-muted-foreground hover:underline">{w.ref}</Link></span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {b.decided_by_name ? `${b.check_status === 'rejected' ? 'Rejected' : 'Approved'} by ${b.decided_by_name}${b.decision_reason ? `: “${b.decision_reason}”` : ''}` : 'Passed the check'} · {day((b.decided_at ?? b.bill_date).slice(0, 10))}
                  </span>
                </span>
                {n(b.caught) > 0 && <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', b.check_status === 'rejected' ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-muted text-muted-foreground')}>{b.check_status === 'rejected' ? `${rupees(n(b.caught))} stopped` : `${rupees(n(b.caught))} accepted`}</span>}
                <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', CHECK_LOOK[b.check_status].chip)}>{CHECK_LOOK[b.check_status].label}</span>
                <span className="w-24 text-right font-semibold tabular-nums">{rupees(n(b.gross))}</span>
              </li>
            ))}
          </ul>
          <Pager {...pagedChecked.pager} noun="bills" className="mt-2" />
        </>
      ))}
      {deciding && <DecideDialog bill={deciding.bill} decision={deciding.decision} onOpenChange={(o) => !o && setDeciding(null)} />}
    </div>
  )
}

/** Each bill line against its work order line: billed so far against measured (red past it), the rate against the agreed
 * one. The check's own words stay under it. */
function BillLines({ bill, wo }: { bill: WoBill; wo?: WorkOrder }) {
  return (
    <div className="mt-3 flex flex-col gap-2.5 rounded-lg bg-muted/40 p-3">
      {bill.lines.map((l) => {
        const line = wo?.lines.find((x) => x.id === l.line_id)
        const measured = n(line?.measured)
        const billed = n(line?.billed)
        const agreed = n(line?.quantity)
        const top = Math.max(measured, billed, agreed, 1)
        const over = billed > measured
        const dear = n(l.rate) > n(l.agreed_rate)
        return (
          <div key={l.line_id} className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
              <span className="font-medium">{l.description}</span>
              <span className="flex items-center gap-2 text-xs tabular-nums">
                <span>{Number(l.quantity).toLocaleString('en-IN')} {l.unit} this bill</span>
                <span className={cn('rounded-full px-2 py-0.5 font-semibold', dear ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200' : 'bg-background')}>₹{Number(l.rate).toLocaleString('en-IN')}{dear ? ` · agreed ₹${Number(l.agreed_rate).toLocaleString('en-IN')}` : ''}</span>
              </span>
            </div>
            {line && (
              <>
                <span className="relative block h-2.5 overflow-hidden rounded-full bg-background" role="img" aria-label={`Billed ${billed} of ${measured} measured, ${agreed} agreed`}>
                  <span className="absolute inset-y-0 left-0 bg-emerald-500/70" style={{ width: `${Math.min(measured, billed) / top * 100}%` }} />
                  {over && <span className="absolute inset-y-0 bg-red-500" style={{ left: `${measured / top * 100}%`, width: `${(billed - measured) / top * 100}%` }} />}
                  {!over && billed < measured && <span className="absolute inset-y-0 bg-emerald-200 dark:bg-emerald-900" style={{ left: `${billed / top * 100}%`, width: `${(measured - billed) / top * 100}%` }} />}
                  <span className="absolute inset-y-0 w-0.5 bg-foreground/60" style={{ left: `calc(${agreed / top * 100}% - 1px)` }} title="Agreed" />
                </span>
                <span className="flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground tabular-nums">
                  <span>Billed <strong className={cn('text-foreground', over && 'text-destructive')}>{billed.toLocaleString('en-IN')}</strong> · measured <strong className="text-foreground">{measured.toLocaleString('en-IN')}</strong> {l.unit}</span>
                  <span>agreed {agreed.toLocaleString('en-IN')}</span>
                </span>
              </>
            )}
          </div>
        )
      })}
      {bill.flags.length > 0 && <ul className="grid gap-0.5 text-xs text-destructive">{bill.flags.map((f, i) => <li key={i}>⚠ {f.words}</li>)}</ul>}
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
          <Button variant="outline" className="gap-1.5" asChild><a href={waLink(s.vendor.phone, statementText(s, company))} target="_blank" rel="noreferrer"><ActionIcon kind="whatsapp" className="size-4" /> Send on WhatsApp</a></Button>
          <Button className="gap-1.5" onClick={() => window.print()}><ActionIcon kind="pdf" className="size-4" /> Print / PDF</Button>
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
          <Button variant="outline" className="gap-1.5" asChild><a href={waLink(wo.vendor_phone, workOrderText(wo, company))} target="_blank" rel="noreferrer"><ActionIcon kind="whatsapp" className="size-4" /> Send on WhatsApp</a></Button>
          <Button className="gap-1.5" onClick={() => window.print()}><ActionIcon kind="pdf" className="size-4" /> Print / PDF</Button>
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
