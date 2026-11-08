import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlarmClock, ArrowLeft, CircleCheck, Copy, Download, FileText, GitMerge, HandCoins, Link2, MessageCircle, MoreHorizontal, PackageOpen,
  Pencil, Phone, Printer, Power, Receipt, Trash2, TriangleAlert, Undo2, Wallet,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/toast-notification'
import { Callout } from '@/components/dpr-page'
import { FilterSelect } from '@/components/filter-select'
import { VendorTile } from '@/components/orders/order-detail'
import { VendorRates } from '@/components/rates/vendor-rates'
import { BillDeliveriesDialog, MergeVendorDialog, PayVendorDialog, VendorFormDialog } from '@/components/vendors/vendor-dialogs'
import { AgeBar } from '@/components/vendors/vendor-parts'
import { useAuth } from '@/lib/AuthContext'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { MONEY_ROLES } from '@/lib/module-map'
import { mayManageMoney, rupees } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
import { exportCsv } from '@/lib/export'
import { cn } from '@/lib/utils'
import {
  KINDS, LINE_LOOK, applyAdvance, balanceWords, day, deleteVendor, fetchLedger, fetchVendor, num, undoVendorPayment, updateVendor,
  type LedgerLine,
} from '@/lib/vendors'

// CC-09 / CC-10 (8 Nov 2026): one supplier's page, reached from the Suppliers list and from every place a supplier is
// named (expenses, orders, receipts, rates, money). Its account as a statement (running balance, a period brings the
// rest forward, print and export), the open bills with due dates (tick and pay), deliveries with no bill yet (record
// their bill, or put them on one typed earlier), payments (use an advance, undo), what it charged, and its details.

type Tab = 'account' | 'bills' | 'unbilled' | 'payments' | 'rates' | 'details'
type Period = 'all' | 'month' | 'last' | '90d'

const PERIODS: { value: Period; label: string }[] = [
  { value: 'all', label: 'Everything' },
  { value: 'month', label: 'This month' },
  { value: 'last', label: 'Last month' },
  { value: '90d', label: 'Last 3 months' },
]

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function range(p: Period): { date_from?: string; date_to?: string } {
  const now = new Date()
  if (p === 'month') return { date_from: iso(new Date(now.getFullYear(), now.getMonth(), 1)) }
  if (p === 'last') return { date_from: iso(new Date(now.getFullYear(), now.getMonth() - 1, 1)), date_to: iso(new Date(now.getFullYear(), now.getMonth(), 0)) }
  if (p === '90d') return { date_from: iso(new Date(now.getTime() - 89 * 86400000)) }
  return {}
}

function Amount({ value, tone }: { value: string | null | undefined; tone?: string }) {
  if (!value) return <span className="text-muted-foreground/50">—</span>
  return <span className={cn('tabular-nums', tone)}>{rupees(num(value))}</span>
}

export default function VendorPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const { scope } = useScope()
  const role = (me?.role || '').toUpperCase()
  const seesMoney = (MONEY_ROLES as readonly string[]).includes(role)
  const canManage = mayManageMoney(role) && !readOnly
  const projectId = scope.mode === 'project' || scope.mode === 'site' ? scope.projectId : undefined

  const [tab, setTab] = useUrlState<Tab>('tab', seesMoney ? 'account' : 'details')
  const [period, setPeriod] = useUrlState<Period>('period', 'all')
  const [editing, setEditing] = React.useState(false)
  const [merging, setMerging] = React.useState(false)
  const [paying, setPaying] = React.useState<string[] | null>(null)
  const [billing, setBilling] = React.useState<LedgerLine[] | null>(null)
  const [pickBills, setPickBills] = React.useState<string[]>([])
  const [pickDeliveries, setPickDeliveries] = React.useState<string[]>([])

  const vendor = useQuery({ queryKey: ['vendors', 'one', id], queryFn: () => fetchVendor(id), enabled: !!id })
  const ledger = useQuery({
    queryKey: ['finance', 'ledger', id, projectId ?? '', period],
    queryFn: () => fetchLedger(id, { project_id: projectId, ...range(period) }),
    enabled: !!id && seesMoney,
    retry: (n, e: unknown) => n < 2 && ![403, 404].includes((e as { response?: { status?: number } })?.response?.status ?? 0),
  })
  usePageTitle(vendor.data?.name ?? 'Supplier')
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['finance'] })
    queryClient.invalidateQueries({ queryKey: ['vendors'] })
  }
  const toggle = useMutation({
    mutationFn: () => updateVendor(id, { status: vendor.data?.status === 'active' ? 'inactive' : 'active' }),
    onSuccess: (v) => { refresh(); toast.success(v.status === 'active' ? 'Switched on' : 'Switched off') },
  })
  const remove = useMutation({
    mutationFn: () => deleteVendor(id),
    onSuccess: () => { refresh(); toast.success(`${vendor.data?.name} deleted`); navigate('/finance/vendors') },
    onError: (e) => toast.error('Not deleted', apiErrorMessage(e)),
  })
  const undo = useMutation({
    mutationFn: (paymentId: string) => undoVendorPayment(id, paymentId),
    onSuccess: () => { refresh(); toast.success('Payment undone', 'The money is back in its account; the bills it paid are open again.') },
    onError: (e) => toast.error('Not undone', apiErrorMessage(e)),
  })
  const use = useMutation({
    mutationFn: (paymentId: string) => applyAdvance(id, paymentId),
    onSuccess: (r) => { refresh(); toast.success(`Advance used on ${r.bills_paid.length} ${r.bills_paid.length === 1 ? 'bill' : 'bills'}`, num(r.advance_left) ? `${rupees(num(r.advance_left))} still left.` : undefined) },
    onError: (e) => toast.error('Not used', apiErrorMessage(e)),
  })

  if (vendor.isError) {
    const gone = (vendor.error as { response?: { status?: number } })?.response?.status === 404
    return (
      <div className="mx-auto w-full max-w-3xl py-12">
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => navigate('/finance/vendors')}>All suppliers</Button>}>
          {gone ? 'This supplier is not here any more (deleted, or merged into another).' : 'The supplier could not be loaded.'}
        </Callout>
      </div>
    )
  }
  const v = vendor.data
  const L = ledger.data
  const s = L?.summary
  const bal = num(L?.closing)
  const allBalance = num(s?.balance)
  const openBills = s?.open_bills ?? []
  const unbilled = L?.unbilled ?? []
  const payments = (L?.lines ?? []).filter((x) => x.kind === 'payment').slice().reverse()
  const billChoices = (L?.lines ?? []).filter((x) => x.kind === 'bill').slice().reverse()
    .map((x) => ({ id: x.links.expense_id!, label: `${x.title} · ${day(x.date)} · ${rupees(num(x.owe))}` }))
  const tabs: { value: Tab; label: string; count?: number; money?: boolean }[] = [
    { value: 'account', label: 'Account', money: true },
    { value: 'bills', label: 'Bills to pay', count: openBills.length, money: true },
    { value: 'unbilled', label: 'Not billed', count: unbilled.length, money: true },
    { value: 'payments', label: 'Payments', count: payments.length, money: true },
    { value: 'rates', label: 'Rates', money: true },
    { value: 'details', label: 'Details' },
  ]
  const shownTab = !seesMoney ? 'details' : tab

  const exportStatement = () => L && v && exportCsv(`${v.name.replace(/[^\w]+/g, '-')}-statement.csv`,
    ['Date', 'Kind', 'What', 'Detail', 'Ref', 'Project', 'Site', 'Owed', 'Paid', 'Balance'],
    [...(L.brought_forward != null ? [[L.date_from ?? '', 'Brought forward', '', '', '', '', '', '', '', num(L.brought_forward)]] : []),
      ...L.lines.map((x) => [x.date, LINE_LOOK[x.kind].label, x.title, x.detail, x.ref ?? '', x.project ?? '', x.site ?? '', x.owe ? num(x.owe) : '', x.paid ? num(x.paid) : '', num(x.balance)])])

  const tiles: { label: string; value: string; sub?: string; icon: LucideIcon; tone: string; num?: string; go?: Tab }[] = s ? [
    { label: allBalance >= 0 ? 'We owe' : 'Paid ahead', value: rupees(Math.abs(allBalance)), sub: L?.partial ? 'your projects' : v?.credit_days != null ? `${v.credit_days} days credit` : 'no credit days set', icon: HandCoins, tone: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100', go: 'account' },
    { label: 'Overdue', value: rupees(num(s.overdue)), sub: ((n) => (n ? `${n} ${n === 1 ? 'bill' : 'bills'} past due` : 'nothing late'))(openBills.filter((b) => b.overdue_days > 0).length), icon: AlarmClock, tone: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200', num: num(s.overdue) > 0 ? 'text-red-700 dark:text-red-400' : undefined, go: 'bills' },
    { label: 'Delivered, no bill', value: rupees(num(s.unbilled)), sub: s.unbilled_count ? `${s.unbilled_count} deliveries${s.oldest_unbilled ? ` since ${day(s.oldest_unbilled as unknown as string)}` : ''}` : 'all billed', icon: PackageOpen, tone: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', go: 'unbilled' },
    { label: 'Advance unused', value: rupees(num(s.advance_left)), sub: s.last_payment ? `last paid ${day(s.last_payment.date)}` : 'no payment yet', icon: Wallet, tone: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100', go: 'payments' },
  ] : []

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-24 sm:px-2 md:pb-8 print:max-w-none print:pb-0">
      <Link to="/finance/vendors" className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground print:hidden">
        <ArrowLeft className="size-4" /> Suppliers
      </Link>

      {!v ? (
        <Skeleton className="h-16 rounded-xl" />
      ) : (
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <VendorTile id={v.id} name={v.name} size="lg" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-2xl leading-tight font-semibold tracking-tight">{v.name}</h1>
                <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium', KINDS[v.kind ?? 'supplier'].chip)}>{KINDS[v.kind ?? 'supplier'].label}</span>
                {v.status !== 'active' && <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">Switched off</span>}
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                {v.code && <span>{v.code}</span>}
                {v.contact_person && <span>{v.contact_person}</span>}
                {v.phone && <a href={`tel:${v.phone}`} className="inline-flex items-center gap-1 hover:text-foreground"><Phone className="size-3.5" />{v.phone}</a>}
                {v.gstin && <span>GSTIN {v.gstin}</span>}
                {L && <span className="hidden print:inline">Statement as of {day(L.as_of)}</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 print:hidden">
            {canManage && (
              <Button className="gap-1.5 font-semibold" onClick={() => setPaying([])}>
                <HandCoins className="size-4" /> Pay
              </Button>
            )}
            {canManage && unbilled.length > 0 && (
              <Button variant="outline" className="hidden gap-1.5 sm:inline-flex" onClick={() => setBilling(unbilled)}>
                <FileText className="size-4" /> Record bill
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="More"><MoreHorizontal className="size-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {!readOnly && <DropdownMenuItem onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit details</DropdownMenuItem>}
                {canManage && unbilled.length > 0 && <DropdownMenuItem onClick={() => setBilling(unbilled)}><FileText className="size-4" /> Record their bill</DropdownMenuItem>}
                {seesMoney && <DropdownMenuItem onClick={() => window.print()}><Printer className="size-4" /> Print statement</DropdownMenuItem>}
                {seesMoney && <DropdownMenuItem disabled={!L} onClick={exportStatement}><Download className="size-4" /> Export statement</DropdownMenuItem>}
                {v.phone && seesMoney && L && (
                  <DropdownMenuItem asChild>
                    <a href={`https://wa.me/${v.phone.replace(/\D/g, '').replace(/^(\d{10})$/, '91$1')}?text=${encodeURIComponent(`Hello ${v.contact_person ?? v.name}, as per our account the balance is ${rupees(Math.abs(allBalance))} ${allBalance >= 0 ? 'payable to you' : 'advance with you'} as of ${day(L.as_of)}.`)}`} target="_blank" rel="noreferrer">
                      <MessageCircle className="size-4" /> Confirm balance on WhatsApp
                    </a>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => navigate(`/procurement/orders?vendor=${v.id}&tab=all`)}><Receipt className="size-4" /> Its orders</DropdownMenuItem>
                {!readOnly && (
                  <>
                    <DropdownMenuSeparator />
                    {canManage && <DropdownMenuItem onClick={() => setMerging(true)}><GitMerge className="size-4" /> Merge into another…</DropdownMenuItem>}
                    <DropdownMenuItem onClick={() => toggle.mutate()}><Power className="size-4" /> {v.status === 'active' ? 'Switch off' : 'Switch on'}</DropdownMenuItem>
                    {canManage && (
                      <DropdownMenuItem className="text-destructive" onClick={() => window.confirm(`Delete ${v.name}? Only a supplier added by mistake, with nothing recorded, can be deleted.`) && remove.mutate()}>
                        <Trash2 className="size-4" /> Delete
                      </DropdownMenuItem>
                    )}
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
      )}

      {seesMoney && ledger.isError && (
        <Callout tone="draft" icon={TriangleAlert} action={<Button variant="outline" size="sm" className="bg-background" onClick={() => ledger.refetch()}>Try again</Button>}>
          The account could not be loaded.
        </Callout>
      )}

      {seesMoney && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3 print:grid-cols-4">
          {(tiles.length ? tiles : ([null, null, null, null] as (typeof tiles[number] | null)[])).map((t, i) => t ? (
            <button key={t.label} type="button" onClick={() => t.go && setTab(t.go)} className="flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:p-3.5">
              <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl print:hidden', t.tone)}><t.icon className="size-4 sm:size-5" /></span>
              <span className="flex min-w-0 flex-col">
                <span className={cn('truncate text-xl leading-none font-semibold tabular-nums sm:text-2xl', t.num)}>{t.value}</span>
                <span className="truncate text-xs text-foreground/80 sm:text-sm">{t.label}</span>
                {t.sub && <span className="truncate text-xs text-muted-foreground">{t.sub}</span>}
              </span>
            </button>
          ) : <Skeleton key={i} className="h-[74px] rounded-xl" />)}
        </div>
      )}

      {seesMoney && (
        <div role="tablist" aria-label="Sections" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1 print:hidden">
          {tabs.filter((t) => seesMoney || !t.money).map((t) => (
            <button key={t.value} role="tab" type="button" aria-selected={shownTab === t.value} onClick={() => setTab(t.value)}
              className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', shownTab === t.value ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
              {t.label}
              {!!t.count && <span className="rounded-full bg-foreground/10 px-1.5 text-xs tabular-nums">{t.count}</span>}
            </button>
          ))}
        </div>
      )}

      {/* --- Account: the statement ------------------------------------------------------------------------------ */}
      {shownTab === 'account' && (
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2 print:hidden">
            <FilterSelect label="Period" value={period} onChange={(p) => setPeriod(p as Period)} className="w-[170px]" options={PERIODS} />
            <div className="flex items-center gap-2">
              {L?.partial && <span className="text-xs text-muted-foreground">Your projects only, without the company's opening balance</span>}
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => window.print()}><Printer className="size-4" /> Print</Button>
              <Button variant="outline" size="sm" className="gap-1.5" disabled={!L} onClick={exportStatement}><Download className="size-4" /> Export</Button>
            </div>
          </div>
          {!L ? (
            <Skeleton className="h-64 rounded-xl" />
          ) : L.lines.length === 0 && L.brought_forward == null ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <FileText className="size-6 text-muted-foreground" />
              <p className="text-sm font-medium">Nothing in this period</p>
              <p className="max-w-sm text-sm text-muted-foreground">Deliveries with a rate, bills (expenses with this supplier) and payments appear here. Set an opening balance in Edit details to start from what was owed before.</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Date</th>
                    <th className="px-3 py-2 text-left font-medium">What</th>
                    <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Owed</th>
                    <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Paid</th>
                    <th className="px-3 py-2 text-right font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {L.brought_forward != null && (
                    <tr className="bg-muted/20">
                      <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">{day(L.date_from)}</td>
                      <td className="px-3 py-2 font-medium" colSpan={1}>Brought forward</td>
                      <td className="hidden sm:table-cell" /><td className="hidden sm:table-cell" />
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{rupees(num(L.brought_forward))}</td>
                    </tr>
                  )}
                  {L.lines.map((x) => {
                    const open = () => {
                      if (x.links.expense_id) navigate(`/finance/expenses/${x.links.expense_id}`)
                      else if (x.links.order_id) navigate(`/procurement/orders?id=${x.links.order_id}&tab=all`)
                      else if (x.kind === 'payment') setTab('payments')
                    }
                    const clickable = !!(x.links.expense_id || x.links.order_id || x.kind === 'payment')
                    return (
                      <tr key={x.id} className={cn(clickable && 'cursor-pointer hover:bg-muted/30')} onClick={clickable ? open : undefined}>
                        <td className="px-3 py-2 align-top whitespace-nowrap text-muted-foreground">{day(x.date)}</td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <span className={cn('size-2 shrink-0 rounded-full', LINE_LOOK[x.kind].dot)} aria-hidden />
                            <span className="min-w-0 truncate font-medium">{x.title}</span>
                            {x.ref && <span className="hidden shrink-0 text-xs text-muted-foreground md:inline">{x.ref}</span>}
                          </div>
                          <div className="ml-4 line-clamp-2 text-xs text-muted-foreground">
                            {[x.detail, x.project && x.site ? `${x.project} › ${x.site}` : x.project].filter(Boolean).join(' · ')}
                          </div>
                          <div className="ml-4 text-xs sm:hidden">
                            {x.owe && <span className="tabular-nums">+{rupees(num(x.owe))}</span>}
                            {x.paid && <span className="text-green-700 tabular-nums dark:text-green-400">−{rupees(num(x.paid))}</span>}
                          </div>
                        </td>
                        <td className="hidden px-3 py-2 text-right align-top sm:table-cell"><Amount value={x.owe} /></td>
                        <td className="hidden px-3 py-2 text-right align-top sm:table-cell"><Amount value={x.paid} tone="text-green-700 dark:text-green-400" /></td>
                        <td className={cn('px-3 py-2 text-right align-top font-medium tabular-nums', num(x.balance) < 0 && 'text-emerald-700 dark:text-emerald-400')}>
                          {num(x.balance) < 0 ? `+${rupees(-num(x.balance))}` : rupees(num(x.balance))}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot className="border-t-2 bg-muted/30 font-semibold">
                  <tr>
                    <td className="px-3 py-2" colSpan={2}>{balanceWords(L.closing, rupees)}{L.date_to ? ` on ${day(L.date_to)}` : ''}</td>
                    <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{rupees(num(L.period.owed))}</td>
                    <td className="hidden px-3 py-2 text-right text-green-700 tabular-nums sm:table-cell dark:text-green-400">{rupees(num(L.period.paid))}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{rupees(Math.abs(bal))}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          {s && num(s.bills_left) + num(s.unbilled) > 0 && (
            <div className="rounded-xl border bg-card p-3 print:hidden">
              <div className="mb-2 text-sm font-medium">How long it has waited</div>
              <AgeBar buckets={s.buckets} />
            </div>
          )}
        </section>
      )}

      {/* --- Bills to pay ---------------------------------------------------------------------------------------- */}
      {shownTab === 'bills' && (
        <section className="flex flex-col gap-3">
          {openBills.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <CircleCheck className="size-6 text-success" />
              <p className="text-sm font-medium">No bill waiting</p>
              <p className="max-w-sm text-sm text-muted-foreground">A bill is an expense recorded with this supplier, or their bill for deliveries (Not billed › Record bill).</p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-primary" checked={pickBills.length === openBills.length} onChange={(e) => setPickBills(e.target.checked ? openBills.map((b) => b.id) : [])} />
                  {pickBills.length ? `${pickBills.length} picked · ${rupees(openBills.filter((b) => pickBills.includes(b.id)).reduce((n, b) => n + num(b.left), 0))}` : 'Pick bills to pay'}
                </label>
                {canManage && <Button size="sm" className="gap-1.5 font-semibold" disabled={!pickBills.length} onClick={() => setPaying(pickBills)}><HandCoins className="size-4" /> Pay picked</Button>}
              </div>
              <ul className="divide-y rounded-xl border bg-card">
                {openBills.map((b) => (
                  <li key={b.id} className="flex items-center gap-3 px-3 py-2.5">
                    <input type="checkbox" aria-label={`Pick ${b.bill_number ?? b.number}`} className="size-4 accent-primary" checked={pickBills.includes(b.id)} onChange={() => setPickBills((x) => (x.includes(b.id) ? x.filter((y) => y !== b.id) : [...x, b.id]))} />
                    <Link to={`/finance/expenses/${b.id}`} className="min-w-0 flex-1">
                      <span className="block truncate font-medium hover:underline">{b.bill_number ? `Bill ${b.bill_number}` : b.description || 'Bill'} <span className="text-xs font-normal text-muted-foreground">{b.number}</span></span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {day(b.date)}{b.due ? ` · due ${day(b.due)}` : ''}{b.project ? ` · ${b.project}${b.site ? ` › ${b.site}` : ''}` : ''}{b.deliveries ? ` · ${b.deliveries} deliveries` : ''}
                        {num(b.paid) > 0 ? ` · ${rupees(num(b.paid))} of ${rupees(num(b.amount))} paid` : ''}
                      </span>
                    </Link>
                    {b.mismatches > 0 && (
                      <span className="hidden shrink-0 rounded bg-draft-soft px-1.5 py-0.5 text-xs font-medium text-draft sm:inline" title="Open the bill to see what differs">
                        ⚠ {b.mismatches} not as delivered
                      </span>
                    )}
                    <span className="flex shrink-0 flex-col items-end">
                      <span className="font-semibold tabular-nums">{rupees(num(b.left))}</span>
                      {b.overdue_days > 0 ? <span className="text-xs font-semibold text-destructive">{b.overdue_days} days late</span> : <span className="text-xs text-muted-foreground">{b.age_days} days old</span>}
                    </span>
                    {canManage && <Button size="sm" variant="outline" className="shrink-0" onClick={() => setPaying([b.id])}>Pay</Button>}
                  </li>
                ))}
              </ul>
              {num(s?.advance_left) > 0 && (
                <Callout tone="info" icon={Wallet}>{v?.name} holds {rupees(num(s?.advance_left))} of advances not used yet: Payments › Use on bills.</Callout>
              )}
            </>
          )}
        </section>
      )}

      {/* --- Not billed ------------------------------------------------------------------------------------------ */}
      {shownTab === 'unbilled' && (
        <section className="flex flex-col gap-3">
          {unbilled.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <CircleCheck className="size-6 text-success" />
              <p className="text-sm font-medium">Every delivery with a rate is on a bill</p>
            </div>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">Delivered with a rate, no bill yet: owed at the site's rate until their bill comes. When it comes, tick the deliveries on it and record it; or put them on a bill already typed as an expense, so nothing is counted twice.</p>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-primary" checked={pickDeliveries.length === unbilled.length} onChange={(e) => setPickDeliveries(e.target.checked ? unbilled.map((d) => d.id) : [])} />
                  {pickDeliveries.length ? `${pickDeliveries.length} picked · ${rupees(unbilled.filter((d) => pickDeliveries.includes(d.id)).reduce((n, d) => n + num(d.owe), 0))}` : 'Pick the deliveries on their bill'}
                </label>
                {canManage && (
                  <Button size="sm" className="gap-1.5 font-semibold" disabled={!pickDeliveries.length} onClick={() => setBilling(unbilled.filter((d) => pickDeliveries.includes(d.id)))}>
                    <Link2 className="size-4" /> Bill these
                  </Button>
                )}
              </div>
              <ul className="divide-y rounded-xl border bg-card">
                {unbilled.map((d) => (
                  <li key={d.id} className="flex items-center gap-3 px-3 py-2.5">
                    <input type="checkbox" aria-label={`Pick ${d.title}`} className="size-4 accent-primary" checked={pickDeliveries.includes(d.id)} onChange={() => setPickDeliveries((x) => (x.includes(d.id) ? x.filter((y) => y !== d.id) : [...x, d.id]))} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{d.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {day(d.date)} · {d.detail.replace('Delivered, not billed yet', '').replace(/^ @ /, '@ ')}{d.project ? ` · ${d.project}${d.site ? ` › ${d.site}` : ''}` : ''}
                        {d.ref && d.links.order_id && <> · <Link to={`/procurement/orders?id=${d.links.order_id}&tab=all`} className="underline-offset-2 hover:underline">{d.ref}</Link></>}
                      </span>
                    </span>
                    <span className="shrink-0 font-semibold tabular-nums">{rupees(num(d.owe))}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {/* --- Payments -------------------------------------------------------------------------------------------- */}
      {shownTab === 'payments' && (
        <section className="flex flex-col gap-3">
          {payments.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Wallet className="size-6 text-muted-foreground" />
              <p className="text-sm font-medium">No payment in this period</p>
              {canManage && <Button size="sm" className="mt-1 gap-1.5" onClick={() => setPaying([])}><HandCoins className="size-4" /> Pay {v?.name.split(' ')[0]}</Button>}
            </div>
          ) : (
            <ul className="divide-y rounded-xl border bg-card">
              {payments.map((p) => {
                const left = num(p.advance_left)
                return (
                  <li key={p.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                    <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200"><Wallet className="size-4" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{rupees(num(p.paid))} · {day(p.date)}</span>
                      <span className="block truncate text-xs text-muted-foreground">{p.detail}{p.recorded_by ? ` · by ${p.recorded_by}` : ''}</span>
                    </span>
                    {p.on_account && left > 0 && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-xs font-medium text-sky-900 dark:bg-sky-950 dark:text-sky-100">{rupees(left)} unused</span>}
                    <span className="flex shrink-0 gap-1">
                      {canManage && p.on_account && left > 0 && openBills.length > 0 && (
                        <Button size="sm" variant="outline" disabled={use.isPending} onClick={() => use.mutate(p.links.payment_id!)}>Use on bills</Button>
                      )}
                      {p.links.expense_id && !p.on_account && (
                        <Button size="sm" variant="ghost" onClick={() => navigate(`/finance/expenses/${p.links.expense_id}`)}>Open bill</Button>
                      )}
                      {canManage && p.on_account && (
                        <Button size="icon" variant="ghost" className="size-8 text-muted-foreground" title="Undo this payment" aria-label="Undo this payment" disabled={undo.isPending}
                          onClick={() => window.confirm(`Undo the payment of ${rupees(num(p.paid))}? The money goes back to its account and the bills it paid are open again.`) && undo.mutate(p.links.payment_id!)}>
                          <Undo2 className="size-4" />
                        </Button>
                      )}
                    </span>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">A payment against one bill is undone from that bill (Expenses). Undoing a payment made here opens the bills it paid again and returns the money.</p>
        </section>
      )}

      {shownTab === 'rates' && v && <div className="rounded-xl border bg-card"><VendorRates vendorId={v.id} /></div>}

      {/* --- Details --------------------------------------------------------------------------------------------- */}
      {shownTab === 'details' && v && (
        <section className="grid gap-3 md:grid-cols-2">
          <dl className="grid gap-2 rounded-xl border bg-card p-4 text-sm">
            {([
              ['Kind', KINDS[v.kind ?? 'supplier'].label],
              ['Contact person', v.contact_person],
              ['Phone', v.phone],
              ['GSTIN', v.gstin],
              ['Address', v.address],
              ['Credit', v.credit_days != null ? `${v.credit_days} days to pay a bill` : 'Not set (no due dates)'],
              ['Opening balance', v.opening_balance != null ? `${balanceWords(v.opening_balance, rupees)} on ${day(v.opening_balance_date)}` : 'Not set (the account starts with the first record)'],
              ['Notes', v.notes],
            ] as const).map(([k, val]) => (
              <div key={k} className="grid grid-cols-[130px_1fr] gap-2">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="flex items-center gap-1 break-words">
                  {val || <span className="text-muted-foreground/60">—</span>}
                  {k === 'GSTIN' && val && <button type="button" aria-label="Copy GSTIN" className="text-muted-foreground hover:text-foreground" onClick={() => { void navigator.clipboard?.writeText(String(val)); toast.success('GSTIN copied') }}><Copy className="size-3.5" /></button>}
                </dd>
              </div>
            ))}
            {!readOnly && <Button variant="outline" size="sm" className="mt-2 w-fit gap-1.5" onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit details</Button>}
          </dl>
          <div className="grid content-start gap-2 rounded-xl border bg-card p-4 text-sm">
            <div className="font-medium">Recorded with {v.name}</div>
            {([['expenses', 'Expenses and bills', `/finance/expenses?vendor=${v.id}&period=all`], ['deliveries', 'Deliveries', null], ['orders', 'Orders', `/procurement/orders?vendor=${v.id}&tab=all`], ['payments', 'Payments on account', null]] as const).map(([k, label, to]) => (
              <div key={k} className="flex items-center justify-between">
                <span className="text-muted-foreground">{label}</span>
                {to && v.linked[k] ? <Link to={to} className="font-medium tabular-nums hover:underline">{v.linked[k]}</Link> : <span className="font-medium tabular-nums">{v.linked[k]}</span>}
              </div>
            ))}
            <p className="mt-1 text-xs text-muted-foreground">A supplier with records is never deleted: switch it off, or merge it into the right one if it was saved twice.</p>
          </div>
        </section>
      )}

      {v && (
        <>
          <VendorFormDialog open={editing} onOpenChange={setEditing} vendor={v} canSetOpening={canManage} />
          <MergeVendorDialog open={merging} onOpenChange={setMerging} vendor={v} onMerged={(into) => navigate(`/finance/vendors/${into.id}`, { replace: true })} />
          {paying && <PayVendorDialog open onOpenChange={(o) => { if (!o) { setPaying(null); setPickBills([]) } }} vendor={v} preselect={paying} projectId={projectId} />}
          {billing && <BillDeliveriesDialog open onOpenChange={(o) => { if (!o) { setBilling(null); setPickDeliveries([]) } }} vendor={v} deliveries={billing} bills={billChoices} />}
        </>
      )}
    </div>
  )
}
