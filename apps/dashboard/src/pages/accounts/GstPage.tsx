import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, BadgeCheck, CircleAlert, FileWarning, ReceiptText } from 'lucide-react'
import { BooksClosed, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { FlowStrip } from '@/components/accounts/money-kit'
import { SplitBars } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, Segmented } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchGst, formatDay, mayReadBooks, rupees, short, type GstPurchase, type TaxSplit } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-10: the month's GST for the CA. Output tax on RA bills, input tax the company can claim, net payable (GSTR-3B's
// 3.1(a) and 4(A)(5)); IGST or CGST + SGST by place of supply; every bill with its GSTIN; credit missed and why (to fix
// before the return); tied to the GST ledgers. Company-wide (one return per GSTIN). Backend: GET /accounts/gst.
// UXA-07: the return as a sum (collected − claimable = to pay, or credit carried), credit missed in red; every view a
// table on white with its total (sales and suppliers were lists); a bill whose credit is lost carries a red bar.

const TABLE = 'overflow-x-auto rounded-xl border bg-card shadow-xs'
const HEAD = 'border-b bg-muted text-xs text-muted-foreground'

const WHY: Record<NonNullable<GstPurchase['reason']>, string> = {
  no_gstin: 'Supplier has no GSTIN',
  not_included: 'GST said as not included',
  tax_not_below_amount: 'GST not below the amount',
}

function SplitCells({ s }: { s: TaxSplit }) {
  return (
    <>
      <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{Number(s.igst) ? rupees(s.igst) : ''}</td>
      <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{Number(s.cgst) ? rupees(s.cgst) : ''}</td>
      <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{Number(s.sgst) ? rupees(s.sgst) : ''}</td>
    </>
  )
}

type View = 'summary' | 'purchases' | 'sales' | 'suppliers'

export default function GstPage() {
  usePageTitle('GST')
  const { me } = useAuth()
  const periodState = usePeriod('last_month')
  const { period } = periodState
  const allowed = mayReadBooks(me?.role)
  const q = useQuery({ queryKey: ['accounts', 'gst', period], queryFn: () => fetchGst(period), enabled: allowed })
  const [view, setView] = React.useState<View>('summary')
  if (!allowed) return <BooksClosed />
  if (q.isError) return <PageError message="GST could not be loaded." onRetry={() => q.refetch()} back={{ to: '/accounts', label: 'Accounts' }} />
  const d = q.data
  const missed = d?.purchases.filter((p) => !p.claimable) ?? []

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/accounts', label: 'Accounts' }}
        crumb="Accounts"
        title="GST"
        chip={
          d && (
            <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', d.tie.agrees ? 'bg-success-soft text-success' : 'bg-draft-soft text-draft')}>
              {d.tie.agrees ? <BadgeCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />} {d.tie.agrees ? 'Agrees with the books' : 'Differs from the books'}
            </span>
          )
        }
        date={d ? (d.company_gstin ? `GSTIN ${d.company_gstin}` : 'Company GSTIN not set') : undefined}
        action={<div className="flex min-w-0 max-w-full flex-wrap items-center gap-2"><PeriodBar state={periodState} />{d && <ExcelButton path="/accounts/gst/export" params={period} name={`gst-${period.date_from}-to-${period.date_to}`} />}</div>}
      />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <FlowStrip
            guide="gst.stats"
            items={[
              { label: 'GST collected on RA bills', value: rupees(d.output.gst), tone: 'out', sub: `on ${short(d.output.taxable)} billed` },
              { label: 'GST you can claim', value: rupees(d.input.gst), tone: 'in', op: '−', sub: `on ${short(d.input.taxable)} of bills` },
              { label: Number(d.payable) < 0 ? 'Credit carried forward' : 'GST to pay', value: rupees(d.payable), tone: Number(d.payable) < 0 ? 'in' : 'balance', op: '=', sub: 'GSTR-3B 3.1(a) less 4(A)(5)' },
              { label: 'Credit missed', value: rupees(d.missed), tone: Number(d.missed) > 0 ? 'out' : 'plain', sub: Number(d.missed) ? `${missed.length} bill${missed.length === 1 ? '' : 's'}: fix before the return` : 'none' },
            ]}
          />
          {!d.company_gstin && (
            <Callout tone="draft" icon={CircleAlert} action={<Link to="/company?tab=letterhead" className="text-sm underline">Company details</Link>}>
              Add the company's GSTIN to split IGST / CGST + SGST
            </Callout>
          )}
          {d.warnings.map((w) => (
            <Callout key={w.key} tone="draft" icon={FileWarning}>
              <span className="font-medium">
                {w.count} {w.key === 'client_no_gstin' ? `RA bill${w.count === 1 ? '' : 's'}` : `bill${w.count === 1 ? '' : 's'}`} {w.words}
              </span>{' '}
              <span className="tabular-nums">({rupees(w.amount)} GST)</span>
              {w.key === 'supplier_no_gstin' && (
                <button type="button" className="ml-2 underline" onClick={() => setView('purchases')}>
                  See them
                </button>
              )}
            </Callout>
          ))}
          {d.months.length > 1 && (
            <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
              <SplitBars
                up="To pay"
                down="Credit to carry"
                upClass="fill-amber-500"
                downClass="fill-sky-500"
                items={d.months.map((m) => ({
                  key: m.month,
                  label: new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short' }),
                  up: Math.max(0, Number(m.payable)),
                  down: Math.max(0, -Number(m.payable)),
                  detail: (
                    <>
                      {new Date(`${m.month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}: output {short(m.output)}, input {short(m.input)}, net {short(m.payable)}
                    </>
                  ),
                }))}
              />
            </div>
          )}
          <Segmented<View> guide="gst.views"
            label="View"
            value={view}
            options={[
              { value: 'summary', label: 'GSTR-3B summary' },
              { value: 'purchases', label: 'Purchases', count: d.purchases.length },
              { value: 'sales', label: 'Sales', count: d.sales.length },
              { value: 'suppliers', label: 'By supplier GSTIN', count: d.by_supplier.length },
            ]}
            onChange={setView}
          />
          {view === 'summary' && (
            <DprSection icon={ReceiptText} title="In the return's terms">
              <div className={TABLE}>
                <table data-guide="gst.body" className="w-full text-sm">
                  <thead>
                    <tr className={HEAD}>
                      <th className="px-3 py-2 text-left font-medium">Table</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Taxable value</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">IGST</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">CGST</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">SGST</th>
                      <th className="px-3 py-2 text-right font-medium">Total GST</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {[
                      { label: '3.1(a) Outward taxable supplies', s: d.output },
                      { label: '4(A)(5) All other input tax credit', s: d.input },
                    ].map((r) => (
                      <tr key={r.label}>
                        <td className="px-3 py-2">{r.label}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(r.s.taxable)}</td>
                        <SplitCells s={r.s} />
                        <td className="px-3 py-2 text-right font-medium tabular-nums">{rupees(r.s.gst)}</td>
                      </tr>
                    ))}
                    <tr className={cn('border-t-[1.5px] font-semibold', Number(d.payable) < 0 ? 'border-emerald-500/40 bg-emerald-500/[0.06]' : 'border-sky-500/40 bg-sky-500/[0.06]')}>
                      <td className="px-3 py-2.5">{Number(d.payable) < 0 ? 'Credit to carry forward' : 'Net payable'}</td>
                      <td className="hidden sm:table-cell" />
                      <td className="hidden md:table-cell" colSpan={3} />
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.payable)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                Books: Output GST {rupees(d.tie.output_books)}, Input GST {rupees(d.tie.input_books)} for the period
                {d.tie.agrees ? ', the same as above.' : ': different from above.'}
              </p>
            </DprSection>
          )}
          {view === 'purchases' && (
            <DprSection icon={ArrowDownLeft} title="Purchases with GST" meta={d.purchases.length || undefined}>
              {d.purchases.length === 0 ? (
                <p className="text-sm text-muted-foreground">No bill with GST in this period.</p>
              ) : (
                <div className={TABLE}>
                  <table data-guide="gst.body" className="w-full text-sm">
                    <thead>
                      <tr className={HEAD}>
                        <th className="px-3 py-2 text-left font-medium">Bill</th>
                        <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Taxable</th>
                        <th className="hidden px-3 py-2 text-right font-medium md:table-cell">IGST</th>
                        <th className="hidden px-3 py-2 text-right font-medium md:table-cell">CGST</th>
                        <th className="hidden px-3 py-2 text-right font-medium md:table-cell">SGST</th>
                        <th className="px-3 py-2 text-right font-medium">GST</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {d.purchases.map((p) => (
                        <tr key={p.id} className={cn(!p.claimable && 'bg-destructive/5')}>
                          <td className={cn('px-3 py-2', !p.claimable && 'border-l-4 border-l-destructive')}>
                            <Link to={`/finance/expenses/${p.id}`} className="font-medium hover:underline">
                              {p.supplier ?? 'No supplier'}
                            </Link>
                            <span className="block text-xs text-muted-foreground">
                              {[formatDay(p.date), p.number, p.gstin ?? 'no GSTIN', p.project].filter(Boolean).join(' · ')}
                            </span>
                            {!p.claimable && p.reason && <span className="mt-0.5 inline-block rounded bg-destructive/10 px-1.5 text-[11px] font-medium text-destructive">Not claimable: {WHY[p.reason]}</span>}
                          </td>
                          <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(p.taxable)}</td>
                          <SplitCells s={p} />
                          <td className="px-3 py-2 text-right font-medium tabular-nums">{rupees(p.gst)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                        <td className="px-3 py-2.5">
                          {d.purchases.length} {d.purchases.length === 1 ? 'bill' : 'bills'} <span className="font-normal text-muted-foreground">· claimable {rupees(d.input.gst)}</span>
                        </td>
                        <td className="hidden px-3 py-2.5 text-right tabular-nums sm:table-cell">{rupees(d.purchases.reduce((t, p) => t + Number(p.taxable), 0))}</td>
                        <td className="hidden md:table-cell" colSpan={3} />
                        <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.purchases.reduce((t, p) => t + Number(p.gst), 0))}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </DprSection>
          )}
          {view === 'sales' && (
            <DprSection icon={ArrowUpRight} title="RA bills with GST" meta={d.sales.length || undefined}>
              {d.sales.length === 0 ? (
                <p className="text-sm text-muted-foreground">No RA bill sent in this period.</p>
              ) : (
                <div className={TABLE}>
                  <table data-guide="gst.body" className="w-full min-w-[640px] text-sm">
                    <thead>
                      <tr className={HEAD}>
                        <th className="px-3 py-2 text-left font-medium">RA bill</th>
                        <th className="px-3 py-2 text-left font-medium">Client GSTIN</th>
                        <th className="px-3 py-2 text-left font-medium">Rate · type</th>
                        <th className="px-3 py-2 text-right font-medium">Taxable</th>
                        <th className="px-3 py-2 text-right font-medium">GST</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {d.sales.map((s) => (
                        <tr key={s.id}>
                          <td className={cn('px-3 py-2', !s.gstin && 'border-l-4 border-l-draft')}>
                            <Link to={`/billing/ra-bills/${s.id}/document`} className="font-medium hover:underline">
                              {s.ref} · {s.client ?? 'No client'}
                            </Link>
                            <span className="block text-xs text-muted-foreground">{[formatDay(s.date), s.project].filter(Boolean).join(' · ')}</span>
                          </td>
                          <td className={cn('px-3 py-2 text-xs', s.gstin ? 'tabular-nums text-muted-foreground' : 'font-medium text-draft')}>{s.gstin ?? 'No GSTIN'}</td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">
                            {[s.rate ? `${Number(s.rate)}%` : null, Number(s.igst) ? 'IGST' : Number(s.cgst) ? 'CGST + SGST' : null].filter(Boolean).join(' · ') || '—'}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">{rupees(s.taxable)}</td>
                          <td className="px-3 py-2 text-right font-medium tabular-nums text-rose-700 dark:text-rose-400">{rupees(s.gst)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                        <td className="px-3 py-2.5" colSpan={3}>{d.sales.length} {d.sales.length === 1 ? 'RA bill' : 'RA bills'}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.output.taxable)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.output.gst)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </DprSection>
          )}
          {view === 'suppliers' && (
            <DprSection icon={ReceiptText} title="By supplier GSTIN (for matching with GSTR-2B)">
              <div className={TABLE}>
                <table data-guide="gst.body" className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className={HEAD}>
                      <th className="px-3 py-2 text-left font-medium">Supplier</th>
                      <th className="px-3 py-2 text-left font-medium">GSTIN</th>
                      <th className="px-3 py-2 text-right font-medium">Bills</th>
                      <th className="px-3 py-2 text-right font-medium">Taxable</th>
                      <th className="px-3 py-2 text-right font-medium">GST</th>
                      <th className="px-3 py-2 text-right font-medium">Missed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.by_supplier.map((s) => {
                      const lost = Number(s.gst) - Number(s.claimable)
                      return (
                        <tr key={`${s.gstin}-${s.supplier}`} className={cn(lost > 0.005 && 'bg-destructive/5')}>
                          <td className={cn('px-3 py-2 font-medium', lost > 0.005 && 'border-l-4 border-l-destructive')}>{s.supplier}</td>
                          <td className={cn('px-3 py-2 text-xs', s.gstin ? 'tabular-nums text-muted-foreground' : 'font-medium text-destructive')}>{s.gstin ?? 'No GSTIN: add it on the supplier to claim'}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{s.bills}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{rupees(s.taxable)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-emerald-700 dark:text-emerald-400">{rupees(s.gst)}</td>
                          <td className={cn('px-3 py-2 text-right tabular-nums', lost > 0.005 ? 'font-medium text-destructive' : 'text-muted-foreground')}>{lost > 0.005 ? rupees(lost) : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-[1.5px] border-foreground/25 bg-muted/30 font-semibold">
                      <td className="px-3 py-2.5" colSpan={3}>{d.by_supplier.length} {d.by_supplier.length === 1 ? 'supplier' : 'suppliers'}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.by_supplier.reduce((t, x) => t + Number(x.taxable), 0))}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{rupees(d.by_supplier.reduce((t, x) => t + Number(x.gst), 0))}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-destructive">{Number(d.missed) ? rupees(d.missed) : '—'}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </DprSection>
          )}
        </>
      )}
    </div>
  )
}
