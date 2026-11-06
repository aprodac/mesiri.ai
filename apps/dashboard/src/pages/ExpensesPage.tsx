import * as React from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Filter, Image as ImageIcon, MessageSquare, MoreHorizontal, Plus, Receipt, Search, TriangleAlert, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout, PageHeader, StatStrip } from '@/components/dpr-page'
import { FilterSelect, PeriodSelect } from '@/components/filter-select'
import { RecordExpenseDialog } from '@/components/expenses/record-expense-dialog'
import { ExpenseDetailSheet, type ExpenseDetailData } from '@/components/expenses/expense-detail-sheet'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { periodRange, type Period } from '@/lib/period'
import { exportCsv } from '@/lib/export'
import { CHIP } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import { fetchAllExpenseAttachmentsApi, fetchCategoriesApi, fetchExpensesApi, reverseExpenseApi } from '@/lib/api'

// WEB-51 (Ilan, 5 Nov): Finance > Expenses, one page for what used to be Expenses, Receipts and the expense page.
// A list grouped by day, with the real vendor, project, site and number (the old page showed "Direct Payee",
// "Org Wide" and a number made from the id). Filters are dropdowns kept in the address: category, payment, bill
// photo (what Receipts was), source, period, search. A row opens the expense's panel; its menu shows the bill photo
// or takes the expense back. /finance/expenses/:id opens that expense here.

interface Expense {
  id: string
  number: string | null
  amount: number
  category_id: string
  category: string
  vendor: string | null
  project: string | null
  site: string | null
  description: string | null
  date: string
  payment: 'paid' | 'partially_paid' | 'unpaid'
  source: 'whatsapp' | 'web'
  reversed: boolean
  correlation_id: string | null
}

const PAGE = 50
const rupees = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
const PAYMENT = {
  paid: { label: 'Paid', className: 'bg-success-soft text-success' },
  partially_paid: { label: 'Part paid', className: 'bg-draft-soft text-draft' },
  unpaid: { label: 'Unpaid', className: 'bg-draft-soft text-draft' },
} as const

function toExpense(raw: any): Expense {
  return {
    id: String(raw.id),
    number: raw.expense_number ?? null,
    amount: Number(raw.amount) || 0,
    category_id: String(raw.category_id ?? ''),
    category: raw.category_name || 'No category',
    vendor: raw.vendor_name ?? null,
    project: raw.project_name ?? null,
    site: raw.site_name ?? null,
    description: raw.description ?? null,
    date: raw.occurred_date,
    payment: raw.payment_status === 'paid' ? 'paid' : raw.payment_status === 'partially_paid' ? 'partially_paid' : 'unpaid',
    source: raw.source === 'whatsapp' ? 'whatsapp' : 'web',
    reversed: raw.workflow_status === 'reversed',
    correlation_id: raw.correlation_id ?? null,
  }
}

export default function ExpensesPage() {
  usePageTitle('Expenses')
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { id: routeId } = useParams()
  const [params, setParams] = useSearchParams()

  const [q, setQ] = useUrlState<string>('q', '')
  const [category, setCategory] = useUrlState<string>('category', 'all')
  const [payment, setPayment] = useUrlState<string>('payment', 'all')
  const [photo, setPhoto] = useUrlState<string>('photo', 'all')
  const [source, setSource] = useUrlState<string>('source', 'all')
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [shownCount, setShownCount] = React.useState(PAGE)
  const [recordOpen, setRecordOpen] = React.useState(false)
  const [taking, setTaking] = React.useState<Expense | null>(null)
  const [photoUrl, setPhotoUrl] = React.useState<string | null>(null)

  const scoped = {
    project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    site_id: scope.mode === 'site' ? scope.siteId : undefined,
  }
  const list = useQuery({
    queryKey: ['finance', 'expenses', scoped],
    queryFn: async () => ((await fetchExpensesApi(scoped)) as any[]).map(toExpense),
  })
  const photos = useQuery({
    queryKey: ['finance', 'expense-photos', scoped],
    queryFn: async () => {
      const byExpense: Record<string, string> = {}
      for (const a of await fetchAllExpenseAttachmentsApi({ ...scoped, limit: 500 })) byExpense[a.expense_id] ??= a.url
      return byExpense
    },
  })
  const categories = useQuery({ queryKey: ['finance', 'categories'], queryFn: fetchCategoriesApi, staleTime: 60_000 })
  const takeBack = useMutation({
    mutationFn: (e: Expense) => reverseExpenseApi(e.id),
    onSuccess: () => {
      setTaking(null)
      queryClient.invalidateQueries({ queryKey: ['finance'] })
    },
  })

  const { from: rangeFrom, to: rangeTo } = periodRange(period, from, to)
  const needle = q.trim().toLowerCase()
  const expenses = React.useMemo(() => {
    const byPhoto = photos.data ?? {}
    return (list.data ?? [])
      .filter((e) => (!rangeFrom || e.date >= rangeFrom) && (!rangeTo || e.date <= rangeTo))
      .filter((e) => category === 'all' || e.category_id === category)
      .filter((e) => payment === 'all' || e.payment === payment)
      .filter((e) => source === 'all' || e.source === source)
      .filter((e) => photo === 'all' || (photo === 'yes') === !!byPhoto[e.id])
      .filter((e) => !needle || [e.number, e.category, e.vendor, e.description, e.site, e.project].join(' ').toLowerCase().includes(needle))
      .sort((a, b) => b.date.localeCompare(a.date))
  }, [list.data, photos.data, rangeFrom, rangeTo, category, payment, source, photo, needle])
  const live = expenses.filter((e) => !e.reversed)
  const total = live.reduce((n, e) => n + e.amount, 0)
  const unpaid = live.filter((e) => e.payment !== 'paid').reduce((n, e) => n + e.amount, 0)
  const filtered = q !== '' || category !== 'all' || payment !== 'all' || photo !== 'all' || source !== 'all'

  // /finance/expenses/:id (and the old ?id=) opens that expense's panel.
  const openId = routeId ?? params.get('id')
  const opened = openId ? (list.data ?? []).find((e) => e.id === openId) ?? null : null
  const open = (e: Expense) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    next.set('id', e.id)
    return next
  })
  const close = () => {
    if (routeId) navigate(`/finance/expenses?${params.toString()}`, { replace: true })
    else setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.delete('id')
      return next
    })
  }
  const detail: ExpenseDetailData | null = opened && {
    id: opened.id,
    number: opened.number,
    amount: opened.amount,
    category_name: opened.category,
    category_id: opened.category_id || undefined,
    vendor_name: opened.vendor,
    project_name: opened.project,
    site_name: opened.site,
    date: opened.date,
    payment_label: PAYMENT[opened.payment].label,
    payment_class: PAYMENT[opened.payment].className,
    source: opened.source,
    reversed: opened.reversed,
    description: opened.description,
  }

  const exportRows = (rows: Expense[]) =>
    exportCsv(
      'expenses.csv',
      ['Number', 'Date', 'Category', 'Vendor', 'Project', 'Site', 'Description', 'Amount', 'Payment', 'From', 'Taken back'],
      rows.map((e) => [e.number ?? '', e.date, e.category, e.vendor ?? '', e.project ?? '', e.site ?? '', e.description ?? '', e.amount, PAYMENT[e.payment].label, e.source === 'whatsapp' ? 'WhatsApp' : 'Dashboard', e.reversed ? 'yes' : '']),
    )

  const days = React.useMemo(() => {
    const out: { date: string; rows: Expense[] }[] = []
    for (const e of expenses.slice(0, shownCount)) {
      const last = out[out.length - 1]
      if (last?.date === e.date) last.rows.push(e)
      else out.push({ date: e.date, rows: [e] })
    }
    return out
  }, [expenses, shownCount])

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 pb-8 sm:px-2">
      <PageHeader
        title="Expenses"
        actions={
          <>
            <Button size="sm" variant="outline" className="gap-1.5" disabled={expenses.length === 0} onClick={() => exportRows(expenses)}>
              <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
            </Button>
            {!readOnly && (
              <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setRecordOpen(true)}>
                <Plus className="size-4" /> Record expense
              </Button>
            )}
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" aria-label="Search expenses" className="h-8 w-[160px] pl-8" />
        </div>
        <FilterSelect
          label="Category"
          value={category}
          onChange={setCategory}
          icon={Filter}
          className="w-[160px]"
          options={[{ value: 'all', label: 'All categories' }, ...(categories.data ?? []).map((c) => ({ value: String(c.id), label: c.name }))]}
        />
        <FilterSelect
          label="Payment"
          value={payment}
          onChange={setPayment}
          className="w-[130px]"
          options={[
            { value: 'all', label: 'Paid or not' },
            { value: 'unpaid', label: 'Unpaid' },
            { value: 'partially_paid', label: 'Part paid' },
            { value: 'paid', label: 'Paid' },
          ]}
        />
        <FilterSelect
          label="Bill photo"
          value={photo}
          onChange={setPhoto}
          icon={ImageIcon}
          className="w-[150px]"
          options={[
            { value: 'all', label: 'Any bill photo' },
            { value: 'yes', label: 'With bill photo' },
            { value: 'no', label: 'No bill photo' },
          ]}
        />
        <FilterSelect
          label="From"
          value={source}
          onChange={setSource}
          icon={MessageSquare}
          className="w-[140px]"
          options={[
            { value: 'all', label: 'WhatsApp or web' },
            { value: 'whatsapp', label: 'WhatsApp' },
            { value: 'web', label: 'Dashboard' },
          ]}
        />
        <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />
      </div>

      {list.isError ? (
        <Callout
          tone="draft"
          icon={TriangleAlert}
          action={
            <Button variant="outline" size="sm" className="bg-background" onClick={() => list.refetch()}>
              Try again
            </Button>
          }
        >
          The expenses could not be loaded.
        </Callout>
      ) : list.isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 rounded-xl" />
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          <StatStrip
            stats={[
              { label: 'Spent', value: rupees(total), icon: Receipt, hint: `${live.length} ${live.length === 1 ? 'expense' : 'expenses'}` },
              { label: 'Unpaid', value: unpaid ? rupees(unpaid) : '—', tone: unpaid ? 'warn' : 'good', icon: TriangleAlert },
              { label: 'Paid', value: rupees(total - unpaid), tone: 'good', icon: Receipt },
            ]}
          />

          {expenses.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
              <Receipt className="size-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm font-medium">{filtered ? 'No expenses match these filters' : 'No expenses in this period'}</p>
              <p className="max-w-sm text-sm text-muted-foreground">
                {filtered ? '' : 'Send a bill photo or "paid 1500 for tea" on WhatsApp, or record one here.'}
              </p>
              {filtered && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setParams((prev) => {
                      const next = new URLSearchParams(prev)
                      ;['q', 'category', 'payment', 'photo', 'source'].forEach((k) => next.delete(k))
                      return next
                    })
                  }
                >
                  Clear filters
                </Button>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {days.map((day) => (
                <section key={day.date} className="flex flex-col gap-1">
                  <h3 className="flex items-baseline justify-between text-xs font-semibold text-muted-foreground">
                    <span>{dayLabel(day.date)}</span>
                    <span className="tabular-nums">{rupees(day.rows.filter((e) => !e.reversed).reduce((n, e) => n + e.amount, 0))}</span>
                  </h3>
                  <ul className="divide-y rounded-lg border">
                    {day.rows.map((e) => (
                      <li key={e.id} className={cn('relative flex items-start gap-3 px-3 py-2 hover:bg-muted/30', e.reversed && 'opacity-60')}>
                        <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0" onClick={() => open(e)}>
                          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                            <span className={cn('font-medium', e.reversed && 'line-through')}>{e.vendor || e.category}</span>
                            {e.vendor && <span className="text-xs text-muted-foreground">{e.category}</span>}
                            {e.reversed ? (
                              <span className={cn(CHIP, 'bg-muted text-muted-foreground')}>Taken back</span>
                            ) : (
                              e.payment !== 'paid' && <span className={cn(CHIP, PAYMENT[e.payment].className)}>{PAYMENT[e.payment].label}</span>
                            )}
                          </span>
                          <span className="line-clamp-1 text-xs text-muted-foreground">
                            {[e.number, e.site ?? e.project, e.description, e.source === 'whatsapp' ? 'WhatsApp' : null].filter(Boolean).join(' · ')}
                          </span>
                        </button>
                        <span className="flex shrink-0 items-center gap-1">
                          {photos.data?.[e.id] && <ImageIcon className="size-3.5 text-muted-foreground" aria-label="Has a bill photo" />}
                          <span className="font-semibold tabular-nums">{rupees(e.amount)}</span>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button type="button" variant="ghost" size="icon" className="relative z-10 size-8" aria-label={`More for ${e.number ?? e.category}`}>
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-48">
                              <DropdownMenuItem onClick={() => open(e)}>Open</DropdownMenuItem>
                              {photos.data?.[e.id] ? (
                                <DropdownMenuItem
                                  onClick={() => {
                                    const url = photos.data![e.id]
                                    if (/\.pdf(\?|$)/i.test(url)) window.open(url, '_blank', 'noreferrer')
                                    else setPhotoUrl(url)
                                  }}
                                >
                                  Bill
                                </DropdownMenuItem>
                              ) : (
                                !e.reversed && !readOnly && <DropdownMenuItem onClick={() => open(e)}>Add bill</DropdownMenuItem>
                              )}
                              {!e.reversed && !readOnly && (
                                <>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setTaking(e)}>
                                    <Undo2 className="mr-2 size-3.5" /> Take back
                                  </DropdownMenuItem>
                                </>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              {expenses.length > shownCount && (
                <Button variant="outline" className="self-center" onClick={() => setShownCount((n) => n + PAGE)}>
                  Load more ({expenses.length - shownCount} left)
                </Button>
              )}
            </div>
          )}
        </>
      )}

      <RecordExpenseDialog
        open={recordOpen}
        onOpenChange={setRecordOpen}
        scope={scope}
        onExpenseCreated={() => queryClient.invalidateQueries({ queryKey: ['finance'] })}
      />
      <ExpenseDetailSheet
        open={!!detail}
        onOpenChange={(o) => !o && close()}
        expense={detail}
        readOnly={readOnly}
        onOpenVendor={() => {
          if (opened?.vendor) setQ(opened.vendor)
          close()
        }}
        onOpenCategory={(id) => {
          setCategory(id)
          close()
        }}
      />

      <Dialog open={taking !== null} onOpenChange={(o) => !o && setTaking(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Take back {taking?.number ?? 'this expense'}?</DialogTitle>
            <DialogDescription>
              {taking && `${rupees(taking.amount)} · ${taking.vendor ?? taking.category} · ${dayLabel(taking.date)}. `}
              It comes off the list and out of every total, and any payment recorded for it is reversed. To change an expense,
              take it back and record it again.
            </DialogDescription>
          </DialogHeader>
          {takeBack.isError && <p className="text-sm text-destructive">It could not be taken back. Try again.</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setTaking(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={takeBack.isPending} onClick={() => taking && takeBack.mutate(taking)}>
              {takeBack.isPending ? 'Taking back…' : 'Take back'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={photoUrl !== null} onOpenChange={(o) => !o && setPhotoUrl(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Bill</DialogTitle>
          </DialogHeader>
          {photoUrl && <img src={photoUrl} alt="Bill photo" className="max-h-[70vh] w-full rounded-md object-contain" />}
        </DialogContent>
      </Dialog>
    </div>
  )
}
