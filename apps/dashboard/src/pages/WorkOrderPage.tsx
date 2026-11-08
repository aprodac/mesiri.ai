import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, Check, CircleCheck, ClipboardCheck, FileText, HandCoins, HardHat, History, Lock, MessageCircle,
  MoreHorizontal, Pencil, Plus, Ruler, Send, TriangleAlert, Unlock, Wallet, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout } from '@/components/dpr-page'
import { VendorTile } from '@/components/orders/order-detail'
import { VendorLink } from '@/components/vendors/vendor-parts'
import { PayVendorDialog } from '@/components/vendors/vendor-dialogs'
import { AdvanceDialog, BillDialog, DecideDialog, MeasureDialog, ReleaseDialog, WorkOrderDialog } from '@/components/subcontracts/dialogs'
import { Progress3 } from '@/components/subcontracts/parts'
import { useAuth } from '@/lib/AuthContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { mayManageMoney, rupees } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
import { day } from '@/lib/vendors'
import { cn } from '@/lib/utils'
import {
  CHECK_LOOK, WO_LOOK, countSiteWork, decideMeasurement, fetchSiteWork, fetchTeamLines, fetchWorkOrder, markTeam, mayGiveWork,
  moveWorkOrder, n, waLink, workOrderText, type WoBill,
} from '@/lib/subcontracts'

// NXT-05/06/07, CC-04 (8 Nov 2026): one work order. What was agreed, done (measured) and billed per line; measurements
// and the site's work updates to count on a line; bills with their check (approve / reject with a reason) and what was
// held, recovered and deducted; advance, retention, pay; the subcontractor's team from attendance; history. Send the
// work order on WhatsApp; print it.

type Tab = 'work' | 'measured' | 'bills' | 'team' | 'history'

export default function WorkOrderPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const office = mayGiveWork(me?.role) && !readOnly
  const pays = mayManageMoney(me?.role) && !readOnly
  const [tab, setTab] = useUrlState<Tab>('tab', 'work')
  const [dialog, setDialog] = React.useState<'' | 'edit' | 'measure' | 'bill' | 'advance' | 'release' | 'pay'>('')
  const [measureLine, setMeasureLine] = React.useState<string | undefined>()
  const [deciding, setDeciding] = React.useState<{ bill: WoBill; decision: 'approve' | 'reject' } | null>(null)

  const q = useQuery({ queryKey: ['subcontracts', 'one', id], queryFn: () => fetchWorkOrder(id), enabled: !!id,
    retry: (c, e: unknown) => c < 2 && (e as { response?: { status?: number } })?.response?.status !== 404 })
  const wo = q.data
  usePageTitle(wo ? `${wo.ref} · ${wo.vendor_name}` : 'Work order')
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ['subcontracts'] }); queryClient.invalidateQueries({ queryKey: ['finance'] }) }
  const move = useMutation({
    mutationFn: (m: 'issue' | 'complete' | 'close' | 'cancel' | 'reopen') => moveWorkOrder(id, m),
    onSuccess: (w) => { refresh(); toast.success(`${w.ref}: ${WO_LOOK[w.status].label}`) },
    onError: (e) => toast.error('Not changed', apiErrorMessage(e)),
  })
  const siteWork = useQuery({ queryKey: ['subcontracts', 'site-work', id], queryFn: () => fetchSiteWork(id), enabled: !!wo && tab === 'measured' && wo.status !== 'draft' })
  const count = useMutation({
    mutationFn: (x: { aq: string; line: string }) => countSiteWork(id, x.aq, x.line),
    onSuccess: () => { refresh(); toast.success('Counted on the work order') },
    onError: (e) => toast.error('Not counted', apiErrorMessage(e)),
  })
  const decide = useMutation({
    mutationFn: (x: { id: string; d: 'confirm' | 'reject' | 'remove' }) => decideMeasurement(x.id, x.d),
    onSuccess: refresh, onError: (e) => toast.error('Not changed', apiErrorMessage(e)),
  })
  const team = useQuery({ queryKey: ['subcontracts', 'team', id], queryFn: () => fetchTeamLines(id), enabled: !!wo && tab === 'team' })
  const mark = useMutation({ mutationFn: (x: { ids: string[]; theirs: boolean }) => markTeam(id, x.ids, x.theirs), onSuccess: () => { refresh(); team.refetch() } })

  if (q.isError) {
    return <div className="mx-auto w-full max-w-3xl py-12"><Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => navigate('/subcontract/work-orders')}>All work orders</Button>}>This work order could not be found.</Callout></div>
  }
  if (!wo) return <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 py-4"><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div>

  const t = wo.totals
  const money = wo.with_money
  const live = wo.status === 'issued' || wo.status === 'completed'
  const bills = wo.bills ?? []
  const waiting = bills.filter((b) => b.check_status === 'waiting' || b.check_status === 'flagged')
  const proposed = wo.measurements.filter((m) => m.status === 'proposed')
  const tabs: { value: Tab; label: string; count?: number; hide?: boolean }[] = [
    { value: 'work', label: 'Work' },
    { value: 'measured', label: 'Measured', count: proposed.length || undefined },
    { value: 'bills', label: 'Bills', count: waiting.length || undefined, hide: !money },
    { value: 'team', label: 'Team on site' },
    { value: 'history', label: 'History' },
  ]
  const company = me?.organization_name ?? 'Mesiri'

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <Link to="/subcontract/work-orders" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Work orders</Link>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <VendorTile id={wo.vendor_id} name={wo.vendor_name} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl leading-tight font-semibold tracking-tight tabular-nums">{wo.ref}</h1>
              <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium', WO_LOOK[wo.status].chip)}>{WO_LOOK[wo.status].label}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
              <VendorLink id={wo.vendor_id} name={wo.vendor_name} className="font-medium text-foreground" tab="account" />
              {wo.title && <span>· {wo.title}</span>}
              <span>· {[wo.project_name, wo.site_name].filter(Boolean).join(' › ')}</span>
              {wo.start_date && <span>· {day(wo.start_date)}{wo.end_date ? ` – ${day(wo.end_date)}` : ''}</span>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {wo.status === 'draft' && office && <Button className="gap-1.5 font-semibold" disabled={move.isPending} onClick={() => move.mutate('issue')}><Send className="size-4" /> Issue</Button>}
          {live && <Button variant={money ? 'outline' : 'default'} className="gap-1.5" onClick={() => { setMeasureLine(undefined); setDialog('measure') }}><Ruler className="size-4" /> Measure</Button>}
          {live && money && <Button className="gap-1.5 font-semibold" onClick={() => setDialog('bill')}><ClipboardCheck className="size-4" /> Record bill</Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="More"><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onClick={() => window.open(`/subcontract/work-orders/${wo.id}/document`, '_blank')}><FileText className="size-4" /> Work order document</DropdownMenuItem>
              <DropdownMenuItem asChild><a href={waLink(wo.vendor_phone, workOrderText(wo, company))} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send to {wo.vendor_name.split(' ')[0]} on WhatsApp</a></DropdownMenuItem>
              {office && wo.status !== 'closed' && wo.status !== 'cancelled' && <DropdownMenuItem onClick={() => setDialog('edit')}><Pencil className="size-4" /> Edit</DropdownMenuItem>}
              {pays && (wo.status === 'draft' || wo.status === 'issued') && <DropdownMenuItem onClick={() => setDialog('advance')}><Wallet className="size-4" /> Give advance</DropdownMenuItem>}
              {pays && money && n(t.payable_now) > 0 && <DropdownMenuItem onClick={() => setDialog('pay')}><HandCoins className="size-4" /> Pay {rupees(n(t.payable_now))}</DropdownMenuItem>}
              {pays && money && n(t.retention_held) > 0 && <DropdownMenuItem onClick={() => setDialog('release')}><Unlock className="size-4" /> Release retention</DropdownMenuItem>}
              {office && <DropdownMenuSeparator />}
              {office && wo.status === 'issued' && <DropdownMenuItem onClick={() => move.mutate('complete')}><CircleCheck className="size-4" /> Work done</DropdownMenuItem>}
              {office && (wo.status === 'issued' || wo.status === 'completed') && <DropdownMenuItem onClick={() => window.confirm(`Close ${wo.ref}? No more bills or measurements on it.`) && move.mutate('close')}><Lock className="size-4" /> Close</DropdownMenuItem>}
              {office && ['completed', 'closed', 'cancelled'].includes(wo.status) && <DropdownMenuItem onClick={() => move.mutate('reopen')}><Unlock className="size-4" /> Reopen</DropdownMenuItem>}
              {office && (wo.status === 'draft' || wo.status === 'issued') && <DropdownMenuItem className="text-destructive" onClick={() => window.confirm(`Cancel ${wo.ref}?`) && move.mutate('cancel')}><X className="size-4" /> Cancel</DropdownMenuItem>}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {waiting.length > 0 && money && (
        <Callout tone="draft" icon={AlertTriangle} action={<Button size="sm" variant="outline" className="bg-background" onClick={() => setTab('bills')}>Check {waiting.length === 1 ? 'it' : 'them'}</Button>}>
          {waiting.length} {waiting.length === 1 ? 'bill waits' : 'bills wait'} for a check: {waiting.map((b) => `${b.ref} ${rupees(n(b.gross))}`).join(', ')}.
        </Callout>
      )}
      {proposed.length > 0 && (
        <Callout tone="info" icon={Ruler} action={<Button size="sm" variant="outline" className="bg-background" onClick={() => setTab('measured')}>Confirm</Button>}>
          {wo.vendor_name.split(' ')[0]} reported {proposed.length} {proposed.length === 1 ? 'measurement' : 'measurements'} waiting for your confirmation.
        </Callout>
      )}

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {[
          { label: 'Done', value: `${t.progress_pct}%`, sub: money ? rupees(n(t.measured_value)) : `${wo.lines.length} lines` },
          ...(money ? [
            { label: 'Work order', value: rupees(n(t.value)), sub: `${wo.lines.length} lines` },
            { label: 'Billed', value: rupees(n(t.billed)), sub: `${t.bills} bills · ${t.billed_pct}%` },
            { label: 'Paid', value: rupees(n(t.paid)), sub: n(t.payable_now) ? `${rupees(n(t.payable_now))} payable now` : 'nothing payable now', tone: n(t.payable_now) ? 'text-sky-700 dark:text-sky-300' : '' },
            { label: `Retention ${Number(wo.retention_pct)}%`, value: rupees(n(t.retention_held)), sub: wo.completed_on ? `released after ${day(new Date(new Date(`${wo.completed_on}T00:00:00`).getTime() + wo.defect_days * 86400000).toISOString().slice(0, 10))}` : 'held until the work is done' },
            { label: 'Advance', value: rupees(n(t.advance_left)), sub: `left of ${rupees(n(t.advance_given))} given` },
          ] : []),
        ].map((x) => (
          <div key={x.label} className="rounded-xl border bg-card p-3">
            <div className="text-xs text-muted-foreground">{x.label}</div>
            <div className={cn('text-lg font-semibold tabular-nums', 'tone' in x && x.tone)}>{x.value}</div>
            <div className="truncate text-xs text-muted-foreground">{x.sub}</div>
          </div>
        ))}
      </section>

      <div role="tablist" aria-label="Sections" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
        {tabs.filter((x) => !x.hide).map((x) => (
          <button key={x.value} role="tab" type="button" aria-selected={tab === x.value} onClick={() => setTab(x.value)}
            className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm', tab === x.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
            {x.label}{x.count ? <span className="rounded-full bg-draft-soft px-1.5 text-xs text-draft tabular-nums">{x.count}</span> : null}
          </button>
        ))}
      </div>

      {tab === 'work' && (
        <section className="overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr><th className="px-3 py-2 text-left font-medium">Work</th><th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Agreed</th>
                <th className="px-3 py-2 text-left font-medium">Done · billed</th>{money && <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Amount</th>}<th className="w-10" /></tr>
            </thead>
            <tbody className="divide-y">
              {wo.lines.map((l) => {
                const done = n(l.quantity) ? Math.round(n(l.measured) / n(l.quantity) * 100) : 0
                const billed = n(l.quantity) ? Math.round(n(l.billed) / n(l.quantity) * 100) : 0
                return (
                  <tr key={l.id} className="align-top">
                    <td className="px-3 py-2.5">
                      <div className="font-medium">{l.boq_code && <span className="mr-1.5 text-xs text-muted-foreground">{l.boq_code}</span>}{l.description}</div>
                      <div className="text-xs text-muted-foreground sm:hidden">{Number(l.quantity).toLocaleString('en-IN')} {l.unit}{l.rate ? ` @ ₹${Number(l.rate).toLocaleString('en-IN')}` : ''}</div>
                      {(l.over_measured || l.over_agreed) && <div className="mt-0.5 text-xs font-medium text-destructive">⚠ {l.over_agreed ? 'more than agreed' : 'billed more than measured'}</div>}
                    </td>
                    <td className="hidden px-3 py-2.5 text-right tabular-nums sm:table-cell">{Number(l.quantity).toLocaleString('en-IN')} {l.unit}{l.rate && <div className="text-xs text-muted-foreground">₹{Number(l.rate).toLocaleString('en-IN')} / {l.unit}</div>}</td>
                    <td className="w-[40%] px-3 py-2.5">
                      <Progress3 done={done} billed={money ? billed : undefined} />
                      <div className="mt-1 flex flex-wrap justify-between gap-x-2 text-xs text-muted-foreground tabular-nums">
                        <span>{Number(l.measured).toLocaleString('en-IN')} done{n(l.proposed) ? ` (+${Number(l.proposed)} reported)` : ''}{money ? ` · ${Number(l.billed).toLocaleString('en-IN')} billed` : ''}</span>
                        <span>{Number(l.remaining).toLocaleString('en-IN')} {l.unit} left</span>
                      </div>
                    </td>
                    {money && <td className="hidden px-3 py-2.5 text-right tabular-nums md:table-cell">{rupees(n(l.amount))}<div className="text-xs text-muted-foreground">{rupees(n(l.billed_amount))} billed</div></td>}
                    <td className="px-2 py-2">{live && <Button size="icon" variant="ghost" className="size-8" title="Measure this line" aria-label={`Measure ${l.description}`} onClick={() => { setMeasureLine(l.id); setDialog('measure') }}><Plus className="size-4" /></Button>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {(wo.terms || wo.notes || wo.status_note) && <div className="border-t px-3 py-2 text-sm text-muted-foreground">{[wo.terms, wo.notes, wo.status_note].filter(Boolean).join(' · ')}</div>}
        </section>
      )}

      {tab === 'measured' && (
        <section className="flex flex-col gap-3">
          {(siteWork.data ?? []).length > 0 && (
            <div className="flex flex-col gap-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3 dark:border-sky-900 dark:bg-sky-950/30">
              <div className="text-sm font-medium">Work recorded on site that may be this work order’s</div>
              <ul className="divide-y rounded-lg border bg-background text-sm">
                {siteWork.data!.slice(0, 12).map((w) => (
                  <li key={w.activity_quantity_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                    <span className="w-14 shrink-0 text-xs text-muted-foreground">{day(w.date)}</span>
                    <span className="min-w-0 flex-1 truncate">{w.quantity} {w.unit} {w.work}{w.contractor ? ` · ${w.contractor}` : ''}{w.site ? ` · ${w.site}` : ''}</span>
                    {w.likely && <span className="rounded bg-sky-100 px-1.5 text-xs text-sky-900 dark:bg-sky-950 dark:text-sky-100">likely</span>}
                    {w.line_id && <Button size="sm" variant="outline" disabled={count.isPending} onClick={() => count.mutate({ aq: w.activity_quantity_id, line: w.line_id! })}>Count on “{w.line}”</Button>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {wo.measurements.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">
              <Ruler className="size-6" />Nothing measured yet. Measure work on site, or count the site’s work updates above.
            </div>
          ) : (
            <ul className="divide-y rounded-xl border bg-card">
              {wo.measurements.map((m) => (
                <li key={m.id} className={cn('flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm', m.status === 'rejected' && 'opacity-50')}>
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">{day(m.measured_on)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{m.quantity} {m.unit} · {m.description}</span>
                    <span className="block text-xs text-muted-foreground">{[m.from_activity ? 'from the site’s work update' : m.source === 'partner' ? 'reported by the subcontractor' : null, m.who, m.notes].filter(Boolean).join(' · ')}</span>
                  </span>
                  {m.status === 'proposed' ? (
                    <span className="flex gap-1">
                      <Button size="sm" className="gap-1" onClick={() => decide.mutate({ id: m.id, d: 'confirm' })}><Check className="size-4" /> Confirm</Button>
                      <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: m.id, d: 'reject' })}>Reject</Button>
                    </span>
                  ) : m.status === 'confirmed' ? (
                    <Button size="icon" variant="ghost" className="size-8 text-muted-foreground" title="Remove (recorded by mistake)" aria-label="Remove measurement" onClick={() => window.confirm('Remove this measurement?') && decide.mutate({ id: m.id, d: 'remove' })}><X className="size-4" /></Button>
                  ) : <span className="text-xs">rejected</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {tab === 'bills' && money && (
        <section className="flex flex-col gap-2">
          {bills.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground"><ClipboardCheck className="size-6" />No bill yet.{live && <Button size="sm" className="mt-1" onClick={() => setDialog('bill')}>Record bill</Button>}</div>
          ) : bills.slice().reverse().map((b) => (
            <article key={b.id} className={cn('rounded-xl border bg-card p-3', b.check_status === 'rejected' && 'opacity-60')}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{b.ref}</span>
                {b.their_bill_no && <span className="text-xs text-muted-foreground">their {b.their_bill_no}</span>}
                <span className="text-xs text-muted-foreground">{day(b.bill_date)}</span>
                <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', CHECK_LOOK[b.check_status].chip)}>{CHECK_LOOK[b.check_status].label}</span>
                {b.submitted_by_contact && <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[11px] text-violet-900 dark:bg-violet-950 dark:text-violet-100">sent by the subcontractor</span>}
                <span className="ml-auto text-lg font-semibold tabular-nums">{rupees(n(b.gross))}</span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{b.lines.map((l) => `${l.quantity} ${l.unit} ${l.description} @ ₹${Number(l.rate)}${n(l.rate) > n(l.agreed_rate) ? ` (agreed ₹${Number(l.agreed_rate)})` : ''}`).join(' · ')}</div>
              {b.flags.length > 0 && <ul className="mt-2 grid gap-0.5 text-sm text-destructive">{b.flags.map((f, i) => <li key={i}>⚠ {f.words}</li>)}</ul>}
              {b.decision_reason && <p className="mt-1 text-xs">{b.check_status === 'approved' ? 'Approved' : 'Rejected'} by {b.decided_by_name}: “{b.decision_reason}”</p>}
              {(b.check_status === 'passed' || b.check_status === 'approved') && (
                <dl className="mt-2 grid grid-cols-3 gap-x-4 gap-y-1 text-xs sm:grid-cols-6">
                  <div><dt className="text-muted-foreground">Retention</dt><dd className="tabular-nums">{rupees(n(b.retention_amount))}{n(b.retention_released) ? ` (${rupees(n(b.retention_released))} released)` : ''}</dd></div>
                  <div><dt className="text-muted-foreground">Advance back</dt><dd className="tabular-nums">{rupees(n(b.advance_recovered))}</dd></div>
                  <div><dt className="text-muted-foreground">TDS</dt><dd className="tabular-nums">{rupees(n(b.tds_amount))}</dd></div>
                  <div><dt className="text-muted-foreground">Net</dt><dd className="font-semibold tabular-nums">{rupees(n(b.net_payable))}</dd></div>
                  <div><dt className="text-muted-foreground">Paid</dt><dd className="tabular-nums">{rupees(n(b.paid_cash))}</dd></div>
                  <div><dt className="text-muted-foreground">Payable now</dt><dd className="font-semibold text-sky-700 tabular-nums dark:text-sky-300">{rupees(n(b.payable_now))}</dd></div>
                </dl>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                {(b.check_status === 'waiting' || b.check_status === 'flagged') && !readOnly && (
                  <>
                    <Button size="sm" className="gap-1" onClick={() => setDeciding({ bill: b, decision: 'approve' })}><Check className="size-4" /> Approve</Button>
                    <Button size="sm" variant="outline" onClick={() => setDeciding({ bill: b, decision: 'reject' })}>Reject</Button>
                  </>
                )}
                <Button size="sm" variant="ghost" onClick={() => navigate(`/finance/expenses/${b.expense_id}`)}>Open expense</Button>
              </div>
            </article>
          ))}
        </section>
      )}

      {tab === 'team' && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3 text-sm">
            <HardHat className="size-5 text-muted-foreground" />
            <span><span className="font-semibold tabular-nums">{wo.team.man_days}</span> man-days of {wo.vendor_name.split(' ')[0]}’s team on {wo.team.days} days{wo.team.last ? ` · last ${day(wo.team.last)}` : ''}</span>
          </div>
          <p className="text-sm text-muted-foreground">Attendance at this site in the last 30 days. Tick the lines that were this subcontractor’s team: their man-days show here (wages stay in Labour).</p>
          <ul className="divide-y rounded-xl border bg-card text-sm">
            {(team.data ?? []).map((l) => (
              <li key={l.id} className="flex items-center gap-3 px-3 py-2">
                <input type="checkbox" className="size-4 accent-primary" checked={l.theirs} disabled={l.other_team || mark.isPending} onChange={() => mark.mutate({ ids: [l.id], theirs: !l.theirs })} aria-label={`${l.trade} on ${l.date}`} />
                <span className="w-16 shrink-0 text-xs text-muted-foreground">{day(l.date)}</span>
                <span className="flex-1">{l.headcount} × {l.trade}{l.site ? ` · ${l.site}` : ''}</span>
                {l.other_team && <span className="text-xs text-muted-foreground">another team</span>}
              </li>
            ))}
            {team.isSuccess && !team.data.length && <li className="px-3 py-6 text-center text-muted-foreground">No attendance at this site in the last 30 days.</li>}
          </ul>
        </section>
      )}

      {tab === 'history' && (
        <ul className="divide-y rounded-xl border bg-card text-sm">
          {wo.history.map((h, i) => (
            <li key={i} className="flex gap-3 px-3 py-2">
              <History className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="flex-1">{h.what}</span>
              <span className="shrink-0 text-right text-xs text-muted-foreground">{h.who}<br />{new Date(h.at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}</span>
            </li>
          ))}
        </ul>
      )}

      <WorkOrderDialog open={dialog === 'edit'} onOpenChange={(o) => !o && setDialog('')} editing={wo} />
      <MeasureDialog open={dialog === 'measure'} onOpenChange={(o) => !o && setDialog('')} wo={wo} lineId={measureLine} />
      {money && <BillDialog open={dialog === 'bill'} onOpenChange={(o) => !o && setDialog('')} wo={wo} />}
      {money && <AdvanceDialog open={dialog === 'advance'} onOpenChange={(o) => !o && setDialog('')} wo={wo} />}
      {money && <ReleaseDialog open={dialog === 'release'} onOpenChange={(o) => !o && setDialog('')} wo={wo} />}
      {dialog === 'pay' && <PayVendorDialog open onOpenChange={(o) => !o && setDialog('')} vendor={{ id: wo.vendor_id, name: wo.vendor_name }} projectId={wo.project_id} />}
      {deciding && <DecideDialog bill={deciding.bill} decision={deciding.decision} onOpenChange={(o) => !o && setDeciding(null)} />}
    </div>
  )
}
