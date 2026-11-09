import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronLeft, ChevronRight, Copy, HandCoins, MessageCircle, Plus, RotateCcw, TriangleAlert, Trash2, Wallet } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { Callout, EmptyState, LinkedStrip, ModuleTitle, StatStrip } from '@/components/page/page-kit'
import { fetchAccountsApi } from '@/lib/api'
import { useSiteOptions, errorWords } from '@/lib/equipment'
import {
  approveWageSheet,
  editWageRow,
  inr,
  n,
  openWageSheet,
  payWages,
  periodLabel,
  reopenWageSheet,
  shiftDate,
  slipLink,
  type Deduction,
  type WageRow,
  type WageSheet,
} from '@/lib/labour-pay'
import { wageRowLinks } from '@/lib/links'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// LW-04 / LW-05 (plan docs/plans/wages-and-labour-plan.md): a site's pay week. Days come from attendance, never
// typed; the payer sets advance recovery and deductions, approves, then pays from a money account and sends each
// person or contractor their slip.

const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

type Account = { id: string; name: string; account_type: string; status?: string }

export default function WagesPage() {
  usePageTitle('Wages')
  const toast = useToast()
  const qc = useQueryClient()
  const readOnly = useReadOnly()
  const { scope } = useScope()
  const sites = useSiteOptions()
  const [picked, setPicked] = useUrlState<string>('at', '')
  const [date, setDate] = useUrlState<string>('week', '')
  const [openRow, setOpenRow] = React.useState<string | null>(null)
  const [paying, setPaying] = React.useState<{ row?: WageRow } | null>(null)

  const siteId = scope.mode === 'site' ? scope.siteId : picked || (scope.mode === 'project' ? '' : sites.data?.[0]?.id ?? '')
  const projectId = scope.mode === 'project' && !picked ? scope.projectId : null
  const day = date || today()
  const key = ['wages', siteId, projectId, day]
  const sheet = useQuery({
    queryKey: key,
    queryFn: () => openWageSheet({ site_id: siteId || null, project_id: siteId ? null : projectId, date: day }),
    enabled: !!(siteId || projectId),
    retry: false,
  })
  const put = (s: WageSheet) => {
    qc.setQueryData(key, s)
    qc.invalidateQueries({ queryKey: ['home'] })
  }
  const fail = (title: string) => (e: unknown) => toast.error(title, errorWords(e))
  const approve = useMutation({ mutationFn: (id: string) => approveWageSheet(id), onSuccess: (s) => { put(s); toast.success('Approved', 'The week can be paid now.') }, onError: fail('Could not approve') })
  const reopen = useMutation({ mutationFn: (id: string) => reopenWageSheet(id), onSuccess: (s) => { put(s); toast.success('Back to draft') }, onError: fail('Could not reopen') })

  const s = sheet.data
  const row = s?.rows.find((r) => r.id === openRow) ?? null
  const draft = s?.status === 'draft'

  const siteSelect = scope.mode !== 'site' && (
    <select
      aria-label="Site"
      value={siteId}
      onChange={(e) => setPicked(e.target.value)}
      className="h-9 rounded-lg border bg-background px-2 text-sm"
    >
      {scope.mode === 'project' && <option value="">Whole project</option>}
      {(sites.data ?? []).filter((x) => scope.mode !== 'project' || x.projectId === scope.projectId).map((x) => (
        <option key={x.id} value={x.id}>{x.projectName} › {x.name}</option>
      ))}
    </select>
  )

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <ModuleTitle icon={Wallet} title="Wages" chip={s && (
          <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', draft ? 'bg-draft-soft text-draft' : n(s.totals.due) > 0 ? 'bg-info-soft text-info' : 'bg-success-soft text-success')}>
            {draft ? 'Draft' : n(s.totals.due) > 0 ? 'Approved · to pay' : 'Paid'}
          </span>
        )} />
        <div className="flex flex-wrap items-center gap-2">
          {siteSelect}
          <div className="flex items-center rounded-lg border">
            <Button variant="ghost" size="icon" className="size-9" aria-label="Previous week" onClick={() => setDate(shiftDate(s?.period_from ?? day, -1))}><ChevronLeft className="size-4" /></Button>
            <span className="min-w-28 px-1 text-center text-sm font-medium tabular-nums">{s ? periodLabel(s.period_from, s.period_to) : '…'}</span>
            <Button variant="ghost" size="icon" className="size-9" aria-label="Next week" onClick={() => setDate(shiftDate(s?.period_to ?? day, 1))}><ChevronRight className="size-4" /></Button>
          </div>
          {s && !readOnly && draft && s.rows.length > 0 && (
            <Button className="gap-1.5 font-semibold" disabled={approve.isPending} onClick={() => approve.mutate(s.id)}><CheckCircle2 className="size-4" /> Approve</Button>
          )}
          {s && !readOnly && !draft && n(s.totals.due) > 0 && (
            <Button className="gap-1.5 font-semibold" onClick={() => setPaying({})}><HandCoins className="size-4" /> Pay {inr(s.totals.due)}</Button>
          )}
          {s && !readOnly && !draft && n(s.totals.paid) === 0 && (
            <Button variant="outline" className="gap-1.5" disabled={reopen.isPending} onClick={() => reopen.mutate(s.id)}><RotateCcw className="size-4" /> Reopen</Button>
          )}
        </div>
      </header>

      {!siteId && !projectId ? (
        <EmptyState icon={Wallet} title="Pick a site" about="Wages are worked out per site and week, from the attendance the site sends." />
      ) : sheet.isError ? (
        <Callout tone="draft" icon={TriangleAlert}>{errorWords(sheet.error)}</Callout>
      ) : !s ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : (
        <>
          {s.changed.length > 0 && (
            <Callout tone="draft" icon={TriangleAlert} action={n(s.totals.paid) === 0 && !readOnly ? <Button size="sm" variant="outline" className="bg-background" onClick={() => reopen.mutate(s.id)}>Reopen and update</Button> : undefined}>
              Attendance changed after this week was approved: {s.changed.map((c) => `${c.payee_name} ${c.difference > 0 ? '+' : '−'}${inr(Math.abs(c.difference))}`).join(', ')}.
              {n(s.totals.paid) > 0 && " Part of it is paid, so each difference goes on next week's sheet."}
            </Callout>
          )}
          {n(s.totals.unpriced_man_days) > 0 && (
            <Callout tone="info" icon={TriangleAlert}>{n(s.totals.unpriced_man_days)} man-days have no wage, so they are not in the wages. Add the wage on the worker or in the attendance.</Callout>
          )}
          <StatStrip
            stats={[
              { label: 'Man-days', value: n(s.totals.man_days).toLocaleString('en-IN') },
              { label: 'Wages + overtime', value: inr(n(s.totals.gross) + n(s.totals.overtime_amount)) },
              { label: 'Advance back', value: inr(s.totals.advances_recovered) },
              { label: 'Deductions', value: inr(s.totals.deductions) },
              { label: 'To pay', value: inr(s.totals.net), tone: draft ? 'warn' : undefined },
              { label: 'Paid', value: inr(s.totals.paid), tone: !draft && n(s.totals.due) === 0 && n(s.totals.net) > 0 ? 'good' : undefined, hint: n(s.totals.due) > 0 && !draft ? `${inr(s.totals.due)} still due` : undefined },
            ]}
          />
          {s.rows.length === 0 ? (
            <EmptyState icon={Wallet} title="No attendance this week" about="Wages fill in from the attendance the site sends. Nothing was reported for this site and week."
              whatsapp="Suresh team: 4 masons, 2 helpers today" />
          ) : (
            <>
            {/* Phones: one card per payee, the figures that decide the payment. */}
            <ul className="flex flex-col gap-2 sm:hidden">
              {s.rows.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => setOpenRow(r.id)} className="flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{r.payee_name}</span>
                      <span className="block text-xs text-muted-foreground">{n(r.man_days)} man-days · {inr(n(r.gross) + n(r.overtime_amount))}{n(r.advances_recovered) ? ` · −${inr(r.advances_recovered)} advance` : ''}</span>
                    </span>
                    <span className="text-right">
                      <span className={cn('block font-semibold tabular-nums', n(r.net) < 0 && 'text-destructive')}>{n(r.net) < 0 ? `owes ${inr(-n(r.net))}` : inr(r.net)}</span>
                      <span className={cn('block text-xs', n(r.due) > 0 && !draft ? 'text-draft' : 'text-success')}>{n(r.paid) ? `${inr(r.paid)} paid` : draft ? 'draft' : n(r.due) > 0 ? 'to pay' : ''}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto rounded-xl border sm:block">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-right [&>th:first-child]:text-left">
                    <th>Paid to</th><th>Man-days</th><th>Wages</th><th>Overtime</th><th>Advance back</th><th>Deductions</th><th>To pay</th><th>Paid</th><th />
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {s.rows.map((r) => {
                    const ded = r.deductions.reduce((a, d) => a + n(d.amount), 0)  // carried differences included (negative adds)
                    const due = n(r.due)
                    return (
                      <tr key={r.id} className="cursor-pointer hover:bg-muted/40 [&>td]:px-3 [&>td]:py-2 [&>td]:text-right [&>td]:tabular-nums" onClick={() => setOpenRow(r.id)}>
                        <td className="!text-left">
                          <span className="font-medium">{r.payee_name}</span>
                          <span className="block text-xs text-muted-foreground">{r.trades || 'labour'}{r.vendor_id ? ' · team' : ''}</span>
                        </td>
                        <td>{n(r.man_days)}</td>
                        <td>{inr(r.gross)}</td>
                        <td>{n(r.overtime_amount) ? inr(r.overtime_amount) : '—'}</td>
                        <td>{n(r.advances_recovered) ? `−${inr(r.advances_recovered)}` : '—'}</td>
                        <td>{ded ? (ded < 0 ? `+${inr(-ded)}` : `−${inr(ded)}`) : '—'}</td>
                        <td className={cn('font-semibold', n(r.net) < 0 && 'text-destructive')}>{n(r.net) < 0 ? `owes ${inr(-n(r.net))}` : inr(r.net)}</td>
                        <td className={cn(due > 0 && !draft ? 'text-draft' : n(r.paid) > 0 ? 'text-success' : 'text-muted-foreground')}>
                          {n(r.paid) ? inr(r.paid) : '—'}
                        </td>
                        <td onClick={(e) => e.stopPropagation()}>
                          {!draft && due > 0 && !readOnly && <Button size="sm" variant="outline" className="h-7" onClick={() => setPaying({ row: r })}>Pay</Button>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            </>
          )}
        </>
      )}

      {s && row && <RowSheet sheet={s} row={row} onClose={() => setOpenRow(null)} onSaved={put} readOnly={readOnly} />}
      {s && paying && <PayDialog sheet={s} row={paying.row} onClose={() => setPaying(null)} onPaid={(x) => { put(x); setPaying(null); toast.success('Paid', 'The money left the account and the books follow.') }} />}
    </div>
  )
}

function RowSheet({ sheet, row, onClose, onSaved, readOnly }: { sheet: WageSheet; row: WageRow; onClose: () => void; onSaved: (s: WageSheet) => void; readOnly: boolean }) {
  const toast = useToast()
  const draft = sheet.status === 'draft' && !readOnly
  const [recovery, setRecovery] = React.useState(String(n(row.advances_recovered)))
  const carried = row.deductions.filter((d) => d.carry_from)
  const [deductions, setDeductions] = React.useState<Deduction[]>(row.deductions.filter((d) => !d.carry_from))
  React.useEffect(() => {
    setRecovery(String(n(row.advances_recovered)))
    setDeductions(row.deductions.filter((d) => !d.carry_from))
  }, [row])
  const save = useMutation({
    mutationFn: (body: Parameters<typeof editWageRow>[2]) => editWageRow(sheet.id, row.id, body),
    onSuccess: (s) => { onSaved(s); toast.success('Saved') },
    onError: (e) => toast.error('Could not save', errorWords(e)),
  })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(row.slip.replace(/\*/g, ''))
      toast.success('Slip copied')
    } catch {
      toast.error('Could not copy', 'Select the text and copy it.')
    }
  }
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-lg">
        <SheetHeader className="border-b bg-primary/10 px-5 py-4">
          <p className="text-xs text-muted-foreground">{periodLabel(sheet.period_from, sheet.period_to)} · {sheet.site_name ?? sheet.project_name}</p>
          <SheetTitle className="text-xl">{row.payee_name}</SheetTitle>
          <p className="text-2xl font-semibold tabular-nums">{inr(row.net)} <span className="text-sm font-normal text-muted-foreground">to pay{n(row.paid) ? ` · ${inr(row.paid)} paid` : ''}</span></p>
        </SheetHeader>
        <div className="flex flex-col gap-4 px-5 py-4 text-sm">
          <dl className="grid grid-cols-2 gap-2">
            <dt className="text-muted-foreground">Man-days ({row.trades || 'labour'})</dt><dd className="text-right tabular-nums">{n(row.man_days)} on {n(row.days)} days</dd>
            <dt className="text-muted-foreground">Wages</dt><dd className="text-right tabular-nums">{inr(row.gross)}</dd>
            <dt className="text-muted-foreground">Overtime ({n(row.overtime_hours)} h)</dt><dd className="text-right tabular-nums">{inr(row.overtime_amount)}</dd>
            <dt className="text-muted-foreground">Advance still outstanding</dt><dd className="text-right tabular-nums">{inr(row.advance_outstanding)}</dd>
          </dl>

          <section className="flex flex-col gap-2 border-t pt-3">
            <Label htmlFor="rec" className="text-xs font-semibold">Advance taken back this week</Label>
            <div className="flex gap-2">
              <Input id="rec" inputMode="decimal" value={recovery} disabled={!draft} onChange={(e) => setRecovery(e.target.value)} className="h-9" />
              {draft && <Button variant="outline" size="sm" className="h-9" onClick={() => save.mutate({ advances_recovered: n(recovery) })}>Set</Button>}
              {draft && row.recovery_set && <Button variant="ghost" size="sm" className="h-9" onClick={() => save.mutate({ reset_recovery: true })}>All outstanding</Button>}
            </div>
          </section>

          {carried.length > 0 && (
            <section className="flex flex-col gap-1.5 border-t pt-3">
              <h3 className="text-xs font-semibold">From earlier weeks</h3>
              {carried.map((d, i) => (
                <p key={i} className="flex justify-between gap-2"><span className="text-muted-foreground">{d.reason}</span>
                  <span className={cn('tabular-nums font-medium', n(d.amount) < 0 ? 'text-success' : 'text-destructive')}>{n(d.amount) < 0 ? '+' : '−'}{inr(Math.abs(n(d.amount)))}</span></p>
              ))}
            </section>
          )}

          <section className="flex flex-col gap-2 border-t pt-3">
            <h3 className="text-xs font-semibold">Deductions</h3>
            {deductions.length === 0 && <p className="text-muted-foreground">None.</p>}
            {deductions.map((d, i) => (
              <div key={i} className="flex gap-2">
                <Input aria-label="Reason" placeholder="Reason (damage, late, food)" value={d.reason} disabled={!draft} className="h-9" onChange={(e) => setDeductions(deductions.map((x, j) => (j === i ? { ...x, reason: e.target.value } : x)))} />
                <Input aria-label="Amount" inputMode="decimal" value={String(d.amount)} disabled={!draft} className="h-9 w-28" onChange={(e) => setDeductions(deductions.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
                {draft && <Button variant="ghost" size="icon" className="size-9" aria-label="Remove" onClick={() => setDeductions(deductions.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>}
              </div>
            ))}
            {draft && (
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="gap-1" onClick={() => setDeductions([...deductions, { reason: '', amount: '' }])}><Plus className="size-4" /> Deduction</Button>
                <Button size="sm" disabled={save.isPending} onClick={() => save.mutate({ deductions: deductions.filter((d) => d.reason.trim() && n(d.amount) > 0) })}>Save deductions</Button>
              </div>
            )}
          </section>

          {row.payments.length > 0 && (
            <section className="flex flex-col gap-1.5 border-t pt-3">
              <h3 className="text-xs font-semibold">Payments</h3>
              {row.payments.map((p) => (
                <p key={p.id} className="flex justify-between gap-2"><span>{new Date(`${p.paid_on}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} · {p.account_name ?? 'no account'}{p.source === 'whatsapp' ? ' · WhatsApp' : ''}</span><span className="tabular-nums">{inr(p.amount)}</span></p>
              ))}
            </section>
          )}

          <section className="flex flex-col gap-2 border-t pt-3">
            <h3 className="text-xs font-semibold">Payment slip</h3>
            <pre className="whitespace-pre-wrap rounded-lg bg-muted/60 p-3 font-sans text-sm">{row.slip.replace(/\*/g, '')}</pre>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="gap-1.5" onClick={copy}><Copy className="size-4" /> Copy</Button>
              <Button asChild variant="outline" size="sm" className="gap-1.5"><a href={slipLink(row.slip)} target="_blank" rel="noreferrer"><MessageCircle className="size-4" /> Send on WhatsApp</a></Button>
            </div>
          </section>

          <LinkedStrip records={wageRowLinks(sheet, row)} className="border-t pt-3" />
        </div>
      </SheetContent>
    </Sheet>
  )
}

function PayDialog({ sheet, row, onClose, onPaid }: { sheet: WageSheet; row?: WageRow; onClose: () => void; onPaid: (s: WageSheet) => void }) {
  const toast = useToast()
  const accounts = useQuery({ queryKey: ['finance', 'accounts', 'active'], queryFn: () => fetchAccountsApi() as Promise<Account[]> })
  const usable = (accounts.data ?? []).filter((a) => (a.status ?? 'active') === 'active')
  const due = row ? n(row.due) : n(sheet.totals.due)
  const [account, setAccount] = React.useState('')
  const [amount, setAmount] = React.useState(String(due))
  const [paidOn, setPaidOn] = React.useState(today())
  const pay = useMutation({
    mutationFn: () => payWages(sheet.id, { row_id: row?.id, amount: row && n(amount) !== due ? n(amount) : undefined, account_id: account || usable[0]?.id, paid_on: paidOn }),
    onSuccess: onPaid,
    onError: (e) => toast.error('Could not pay', errorWords(e)),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Pay {row ? row.payee_name : `everyone due · ${periodLabel(sheet.period_from, sheet.period_to)}`}</DialogTitle></DialogHeader>
        <div className="grid gap-3 text-sm">
          <div className="grid gap-1.5">
            <Label htmlFor="acct">From</Label>
            <select id="acct" className="h-9 rounded-lg border bg-background px-2" value={account || usable[0]?.id || ''} onChange={(e) => setAccount(e.target.value)}>
              {usable.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
          {row && (
            <div className="grid gap-1.5">
              <Label htmlFor="amt">Amount (due {inr(due)})</Label>
              <Input id="amt" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </div>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="on">Paid on</Label>
            <Input id="on" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button className="font-semibold" disabled={pay.isPending || !usable.length || n(amount) <= 0} onClick={() => pay.mutate()}>Pay {inr(row ? n(amount) : due)}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
