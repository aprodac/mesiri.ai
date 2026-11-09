import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownLeft, ArrowUpRight, BadgeCheck, CircleAlert, FileWarning, Percent, ReceiptText } from 'lucide-react'
import { BooksClosed, BooksTabs, ExcelButton, PeriodBar, usePeriod } from '@/components/accounts/books'
import { SplitBars } from '@/components/accounts/visuals'
import { Callout, DprHeader, DprSection, PageError, Segmented, StatStrip } from '@/components/dpr-page'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { fetchGst, formatDay, mayReadBooks, rupees, short, type GstPurchase, type TaxSplit } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { cn } from '@/lib/utils'

// ACC-10: the month's GST for the CA. Output tax on RA bills, input tax the company can claim, net payable (GSTR-3B's
// 3.1(a) and 4(A)(5)); IGST or CGST + SGST by place of supply; every bill with its GSTIN; credit missed and why (to fix
// before the return); tied to the GST ledgers. Company-wide (one return per GSTIN). Backend: GET /accounts/gst.

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
        action={d && <ExcelButton path="/accounts/gst/export" params={period} name={`gst-${period.date_from}-to-${period.date_to}`} />}
      />
      <BooksTabs current="/accounts/gst" />
      <PeriodBar state={periodState} />
      {!d ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : (
        <>
          <StatStrip
            phoneCols={2}
            stats={[
              { label: 'Output GST (on RA bills)', value: rupees(d.output.gst), icon: ArrowUpRight },
              { label: 'Input GST you can claim', value: rupees(d.input.gst), icon: ArrowDownLeft, tone: 'good' },
              { label: Number(d.payable) < 0 ? 'Credit carried forward' : 'Net GST payable', value: rupees(d.payable), icon: Percent, tone: Number(d.payable) > 0 ? 'warn' : 'good', hint: 'output − claimable input' },
              { label: 'Credit missed', value: rupees(d.missed), icon: FileWarning, tone: Number(d.missed) > 0 ? 'bad' : 'default', hint: Number(d.missed) ? `${missed.length} bill${missed.length === 1 ? '' : 's'}` : 'none' },
            ]}
          />
          {!d.company_gstin && (
            <Callout tone="draft" icon={CircleAlert} action={<Link to="/company?tab=letterhead" className="text-sm underline">Company details</Link>}>
              Add the company's GSTIN (Company details › letterhead) to split GST into IGST or CGST + SGST by the other party's state.
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
            <div className="rounded-xl border px-4 py-3">
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
          <Segmented<View>
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
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
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
                    <tr className="bg-muted/40 font-semibold">
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
                {d.tie.agrees ? ', the same as above.' : ': different from above; a bill was changed after its entry, or a ledger was posted by hand.'} The CA files the return; check purchases against GSTR-2B before claiming.
              </p>
            </DprSection>
          )}
          {view === 'purchases' && (
            <DprSection icon={ArrowDownLeft} title="Purchases with GST" meta={d.purchases.length || undefined}>
              {d.purchases.length === 0 ? (
                <p className="text-sm text-muted-foreground">No bill with GST in this period.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
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
                          <td className="px-3 py-2">
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
                <ul className="divide-y rounded-lg border text-sm">
                  {d.sales.map((s) => (
                    <li key={s.id} className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:items-center sm:gap-4">
                      <span className="min-w-0 flex-1">
                        <Link to={`/billing/ra-bills/${s.id}/document`} className="font-medium hover:underline">
                          {s.ref} · {s.client ?? 'No client'}
                        </Link>
                        <span className="block text-xs text-muted-foreground">
                          {[formatDay(s.date), s.gstin ?? 'client has no GSTIN', s.project, s.rate ? `${Number(s.rate)}%` : null, Number(s.igst) ? 'IGST' : Number(s.cgst) ? 'CGST + SGST' : null].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      <span className="text-xs text-muted-foreground tabular-nums">on {rupees(s.taxable)}</span>
                      <span className="font-medium tabular-nums">{rupees(s.gst)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </DprSection>
          )}
          {view === 'suppliers' && (
            <DprSection icon={ReceiptText} title="By supplier GSTIN (for matching with GSTR-2B)">
              <ul className="divide-y rounded-lg border text-sm">
                {d.by_supplier.map((s) => (
                  <li key={`${s.gstin}-${s.supplier}`} className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:items-center sm:gap-4">
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{s.supplier}</span>
                      <span className={cn('block text-xs', s.gstin ? 'text-muted-foreground' : 'text-destructive')}>
                        {s.gstin ?? 'No GSTIN: add it on the supplier to claim'} · {s.bills} bill{s.bills === 1 ? '' : 's'}
                      </span>
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums">on {rupees(s.taxable)}</span>
                    <span className="tabular-nums">
                      {rupees(s.gst)}
                      {Number(s.claimable) !== Number(s.gst) && <span className="ml-1 text-xs text-destructive">({rupees(Number(s.gst) - Number(s.claimable))} missed)</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </DprSection>
          )}
        </>
      )}
    </div>
  )
}
