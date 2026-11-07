import * as React from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CircleDollarSign, Download, HandCoins, Image as ImageIcon, LayoutGrid, MapPin, MessageSquare, MoreHorizontal, Plus, Receipt, Search, Store,
  TriangleAlert, Undo2, Wallet, Landmark,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Callout } from '@/components/dpr-page'
import { PeriodSelect } from '@/components/filter-select'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { RecordExpenseDialog } from '@/components/expenses/record-expense-dialog'
import { ExpenseDetailSheet, type ExpenseDetailData } from '@/components/expenses/expense-detail-sheet'
import { FullCost } from '@/components/expenses/full-cost'
import { useScope } from '@/lib/ScopeContext'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { usePageTitle } from '@/lib/page-title'
import { periodRange, type Period } from '@/lib/period'
import { exportCsv } from '@/lib/export'
import { CHIP } from '@/lib/site-day'
import { swatch } from '@/lib/requests'
import { cn } from '@/lib/utils'
import { fetchAllExpenseAttachmentsApi, reverseExpenseApi } from '@/lib/api'
import { PAID_VIA, compact, fetchExpenses, mayManageMoney, paidWords, rupees, type Expense, type PaidVia } from '@/lib/expenses'
import { useAuth } from '@/lib/AuthContext'

// WEB-51 (Ilan, 5 Nov) and PRC-18 (7 Nov): Finance > Expenses. Five tiles say what was spent and how it was paid --
// petty cash, direct, owed back to the person who paid, unpaid (decision D3: by the account it was paid from) --
// and each one filters the list. "Where it went" shows the categories and sites the money went to (a bar filters).
// Filters are pills kept in the address; only the chosen period is loaded. A row opens the expense's panel; its menu
// shows the bill or takes the expense back. /finance/expenses/:id opens that expense here.

const PAGE = 50
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

const VIA_ICON: Record<PaidVia, LucideIcon> = { petty_cash: Wallet, direct: Landmark, own_pocket: HandCoins, unpaid: TriangleAlert }
const VIA_TONE: Record<PaidVia, { tone: string; ring: string }> = {
  petty_cash: { tone: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100', ring: 'ring-amber-500' },
  direct: { tone: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100', ring: 'ring-sky-500' },
  own_pocket: { tone: 'bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-100', ring: 'ring-violet-500' },
  unpaid: { tone: 'bg-orange-200 text-orange-950 dark:bg-orange-900 dark:text-orange-100', ring: 'ring-orange-500' },
}

export default function ExpensesPage() {
  usePageTitle('Expenses')
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const { me } = useAuth()
  const canPay = mayManageMoney(me?.role) && !readOnly
  const [payNow, setPayNow] = React.useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { id: routeId } = useParams()
  const [params, setParams] = useSearchParams()

  const [q, setQ] = useUrlState<string>('q', '')
  const [category, setCategory] = useUrlState<string>('category', '')
  const [vendor, setVendor] = useUrlState<string>('vendor', '')
  const [site, setSite] = useUrlState<string>('at', '')
  const [via, setVia] = useUrlState<string>('paid', '')
  const [photo, setPhoto] = useUrlState<string>('photo', '')
  const [source, setSource] = useUrlState<string>('source', '')
  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [shownCount, setShownCount] = React.useState(PAGE)
  const [recordOpen, setRecordOpen] = React.useState(false)
  const [taking, setTaking] = React.useState<Expense | null>(null)
  const [photoUrl, setPhotoUrl] = React.useState<string | null>(null)
  // Old links used 'all' for "no filter".
  const clean = (v: string) => (v === 'all' ? '' : v)

  const { from: rangeFrom, to: rangeTo } = periodRange(period, from, to)
  const scoped = {
    project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    site_id: scope.mode === 'site' ? scope.siteId : undefined,
  }
  const filters = { ...scoped, date_from: rangeFrom, date_to: rangeTo }
  const list = useQuery({ queryKey: ['finance', 'expenses', filters], queryFn: () => fetchExpenses(filters) })
  const photos = useQuery({
    queryKey: ['finance', 'expense-photos', scoped],
    queryFn: async () => {
      const byExpense: Record<string, string> = {}
      for (const a of await fetchAllExpenseAttachmentsApi({ ...scoped, limit: 500 })) byExpense[a.expense_id] ??= a.url
      return byExpense
    },
  })
  const takeBack = useMutation({
    mutationFn: (e: Expense) => reverseExpenseApi(e.id),
    onSuccess: () => {
      setTaking(null)
      queryClient.invalidateQueries({ queryKey: ['finance'] })
    },
  })

  const all = React.useMemo(() => (list.data ?? []).filter((e) => !e.reversed), [list.data])
  const needle = q.trim().toLowerCase()
  const pass = React.useCallback(
    (e: Expense, skip?: string) => {
      const byPhoto = photos.data ?? {}
      if (skip !== 'category' && clean(category) && e.category_id !== clean(category)) return false
      if (skip !== 'vendor' && vendor && e.vendor_id !== vendor) return false
      if (skip !== 'site' && site && (e.site_id ?? `p:${e.project_id}`) !== site) return false
      if (skip !== 'via' && via && e.paid_via !== via) return false
      if (skip !== 'photo' && clean(photo) && (clean(photo) === 'yes') !== !!byPhoto[e.id]) return false
      if (skip !== 'source' && clean(source) && e.source !== clean(source)) return false
      if (needle && ![e.number, e.category, e.vendor, e.description, e.site, e.project, e.account, e.recorded_by].join(' ').toLowerCase().includes(needle)) return false
      return true
    },
    [category, vendor, site, via, photo, source, needle, photos.data],
  )
  const expenses = React.useMemo(() => all.filter((e) => pass(e)).sort((a, b) => b.date.localeCompare(a.date)), [all, pass])
  // The tiles and "where it went" count everything but the payment filter, so a tile keeps its number when chosen.
  const base = React.useMemo(() => all.filter((e) => pass(e, 'via')), [all, pass])
  const sum = (xs: Expense[]) => xs.reduce((n, e) => n + e.amount, 0)
  const byVia = (v: PaidVia) => base.filter((e) => e.paid_via === v)
  const total = sum(base)
  const filtered = !!(q || clean(category) || vendor || site || via || clean(photo) || clean(source))

  const options = React.useMemo(() => {
    const count = (skip: string, test: (e: Expense) => boolean) => all.filter((e) => pass(e, skip) && test(e)).length
    const uniq = <T,>(xs: T[], key: (x: T) => string) => [...new Map(xs.map((x) => [key(x), x])).values()]
    const categories: FilterOption[] = uniq(all, (e) => e.category_id)
      .map((e) => ({ value: e.category_id, label: e.category, count: count('category', (x) => x.category_id === e.category_id) }))
      .sort((a, b) => b.count - a.count)
    const vendors: FilterOption[] = uniq(all.filter((e) => e.vendor_id), (e) => e.vendor_id!)
      .map((e) => ({ value: e.vendor_id!, label: e.vendor!, swatch: swatch(e.vendor_id!), count: count('vendor', (x) => x.vendor_id === e.vendor_id) }))
      .sort((a, b) => b.count - a.count)
    const sites: FilterOption[] = uniq(all, (e) => e.site_id ?? `p:${e.project_id}`)
      .map((e) => {
        const key = e.site_id ?? `p:${e.project_id}`
        return { value: key, label: e.site ? `${e.project ?? ''} › ${e.site}` : `${e.project ?? 'Company'} (no site)`, swatch: swatch(e.project_id ?? key), count: count('site', (x) => (x.site_id ?? `p:${x.project_id}`) === key) }
      })
      .sort((a, b) => a.label.localeCompare(b.label))
    const vias: FilterOption[] = (Object.keys(PAID_VIA) as PaidVia[]).map((v) => ({ value: v, label: PAID_VIA[v].label, dot: PAID_VIA[v].dot, count: count('via', (x) => x.paid_via === v) }))
    const photosOpt: FilterOption[] = [
      { value: 'yes', label: 'With bill photo', count: count('photo', (x) => !!photos.data?.[x.id]) },
      { value: 'no', label: 'No bill photo', count: count('photo', (x) => !photos.data?.[x.id]) },
    ]
    const sources: FilterOption[] = [
      { value: 'whatsapp', label: 'WhatsApp', count: count('source', (x) => x.source === 'whatsapp') },
      { value: 'web', label: 'Dashboard', count: count('source', (x) => x.source === 'web') },
    ]
    return { categories, vendors, sites, vias, photos: photosOpt, sources }
  }, [all, pass, photos.data])

  // "Where it went": the biggest categories and sites in what is shown.
  const breakdown = (key: (e: Expense) => string, label: (e: Expense) => string) => {
    const m = new Map<string, { key: string; label: string; amount: number; n: number }>()
    for (const e of expenses) {
      const k = key(e)
      const row = m.get(k) ?? { key: k, label: label(e), amount: 0, n: 0 }
      row.amount += e.amount
      row.n += 1
      m.set(k, row)
    }
    const rows = [...m.values()].sort((a, b) => b.amount - a.amount)
    return { top: rows.slice(0, 5), rest: rows.slice(5).reduce((n, r) => n + r.amount, 0), restCount: Math.max(0, rows.length - 5) }
  }
  const byCategory = breakdown((e) => e.category_id, (e) => e.category)
  const bySite = breakdown((e) => e.site_id ?? `p:${e.project_id}`, (e) => e.site ?? `${e.project ?? 'Company'} (no site)`)
  const shownTotal = sum(expenses)

  // /finance/expenses/:id (and the old ?id=) opens that expense's panel.
  const openId = routeId ?? params.get('id')
  const opened = openId ? (list.data ?? []).find((e) => e.id === openId) ?? null : null
  const open = (e: Expense) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('id', e.id)
      return next
    })
  const close = () => {
    if (routeId) navigate(`/finance/expenses?${params.toString()}`, { replace: true })
    else
      setParams((prev) => {
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
    payment_label: opened.paid_via === 'own_pocket' || opened.paid_via === 'unpaid' ? PAID_VIA[opened.paid_via].short : opened.payment === 'partially_paid' ? 'Part paid' : 'Paid',
    payment_class: PAID_VIA[opened.paid_via].chip,
    source: opened.source,
    reversed: opened.reversed,
    description: opened.description,
    paid_line: paidWords(opened),
    recorded_by: opened.recorded_by,
    owed_to: opened.paid_via === 'own_pocket' ? opened.recorded_by ?? 'whoever paid' : null,
  }

  const exportRows = (rows: Expense[]) =>
    exportCsv(
      `expenses-${rangeFrom ?? 'all'}-to-${rangeTo ?? 'today'}.csv`,
      ['Number', 'Date', 'Category', 'Vendor', 'Project', 'Site', 'Description', 'Amount', 'Paid', 'Account', 'Payment status', 'Recorded by', 'From', 'Bill photo'],
      rows.map((e) => [
        e.number ?? '', e.date, e.category, e.vendor ?? '', e.project ?? '', e.site ?? '', e.description ?? '', e.amount, PAID_VIA[e.paid_via].label,
        e.account ?? '', e.payment, e.recorded_by ?? '', e.source === 'whatsapp' ? 'WhatsApp' : 'Dashboard', photos.data?.[e.id] ? 'yes' : '',
      ]),
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

  const clearFilters = () =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      ;['q', 'category', 'vendor', 'at', 'paid', 'photo', 'source'].forEach((k) => next.delete(k))
      return next
    })

  const tiles: { value: PaidVia; amount: number; n: number; hint?: string }[] = (['petty_cash', 'direct', 'own_pocket', 'unpaid'] as PaidVia[]).map((v) => {
    const xs = byVia(v)
    const people = v === 'own_pocket' ? new Set(xs.map((e) => e.recorded_by ?? '?')).size : 0
    return { value: v, amount: sum(xs), n: xs.length, hint: v === 'own_pocket' && xs.length ? `to ${people} ${people === 1 ? 'person' : 'people'}` : undefined }
  })

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200">
            <Receipt className="size-5" />
          </span>
          <div>
            <div className="text-xs text-muted-foreground">Finance</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Expenses</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" className="gap-2" disabled={expenses.length === 0} onClick={() => exportRows(expenses)} title="The expenses shown, as a CSV file (opens in Excel)">
            <Download className="size-4" /> <span className="hidden sm:inline">Export</span>
          </Button>
          {!readOnly && (
            <Button className="hidden gap-2 font-semibold md:inline-flex" onClick={() => setRecordOpen(true)}>
              <Plus className="size-4" strokeWidth={2.6} /> Record expense
            </Button>
          )}
        </div>
      </header>

      <FullCost filters={filters} />

      {/* What was spent, and how it was paid (PRC-18). Each payment tile filters the list. */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-5">
        <div className="col-span-2 flex items-center gap-3 rounded-xl border bg-card p-3 sm:p-3.5 lg:col-span-1">
          <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-xl bg-indigo-100 text-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
            <CircleDollarSign className="size-5" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-2xl leading-none font-semibold tabular-nums">{list.isLoading ? '–' : compact(total)}</span>
            <span className="truncate text-sm text-foreground/80">
              Spent · {base.length} {base.length === 1 ? 'expense' : 'expenses'}
            </span>
          </span>
        </div>
        {tiles.map((t) => {
          const on = via === t.value
          const Icon = VIA_ICON[t.value]
          const pct = total > 0 ? Math.round((t.amount / total) * 100) : 0
          return (
            <button
              key={t.value}
              type="button"
              aria-pressed={on}
              onClick={() => setVia(on ? '' : t.value)}
              className={cn('flex flex-col gap-2 rounded-xl border bg-card p-3 text-left transition hover:-translate-y-px sm:p-3.5', on && cn('ring-2', VIA_TONE[t.value].ring))}
            >
              <span className="flex items-center gap-3">
                <span className={cn('inline-flex size-9 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', VIA_TONE[t.value].tone)}>
                  <Icon className="size-4 sm:size-5" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className={cn('truncate text-lg leading-none font-semibold tabular-nums sm:text-2xl', t.value === 'unpaid' && t.amount > 0 && 'text-orange-700 dark:text-orange-400')}>
                    {list.isLoading ? '–' : compact(t.amount)}
                  </span>
                  <span className="truncate text-xs text-muted-foreground sm:text-sm sm:text-foreground/80">{PAID_VIA[t.value].label}</span>
                </span>
              </span>
              <span className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <span className={cn('block h-full rounded-full', PAID_VIA[t.value].dot)} style={{ width: `${pct}%` }} />
                </span>
                <span className="shrink-0 tabular-nums">{t.hint ?? `${t.n} · ${pct}%`}</span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-9 items-center gap-2 rounded-lg border bg-background px-2.5">
          <Search className="size-4 text-muted-foreground" />
          <span className="sr-only">Search expenses</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" className="w-24 bg-transparent text-sm outline-none sm:w-32" />
        </label>
        <FilterPill icon={LayoutGrid} label="Category" allLabel="All categories" value={clean(category)} options={options.categories} onChange={setCategory} />
        <FilterPill icon={Store} label="Supplier" allLabel="Every supplier" value={vendor} options={options.vendors} onChange={setVendor} />
        {scope.mode !== 'site' && options.sites.length > 1 && <FilterPill icon={MapPin} label="Site" allLabel="All sites" value={site} options={options.sites} onChange={setSite} />}
        <FilterPill icon={Wallet} label="Paid" allLabel="However paid" value={via} options={options.vias} onChange={setVia} />
        <FilterPill icon={ImageIcon} label="Bill photo" allLabel="Any bill photo" value={clean(photo)} options={options.photos} onChange={setPhoto} />
        <FilterPill icon={MessageSquare} label="From" allLabel="WhatsApp or web" value={clean(source)} options={options.sources} onChange={setSource} />
        <div className="ml-auto">
          <PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />
        </div>
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
          <Skeleton className="h-24 rounded-xl" />
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : expenses.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center">
          <Receipt className="size-6 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm font-medium">{filtered ? 'No expenses match these filters' : 'No expenses in this period'}</p>
          <p className="max-w-sm text-sm text-muted-foreground">{filtered ? '' : 'Send a bill photo or "paid 1500 for tea" on WhatsApp, or record one here.'}</p>
          {filtered && (
            <Button variant="outline" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-start gap-5 lg:flex-row-reverse">
          {/* Where it went */}
          <aside aria-label="Where the money went" className="flex w-full shrink-0 flex-col gap-3 lg:sticky lg:top-4 lg:w-[340px]">
            <Breakdown title="By category" total={shownTotal} data={byCategory} active={clean(category)} onPick={(k) => setCategory(clean(category) === k ? '' : k)} colour={() => 'bg-indigo-500'} />
            {new Set(expenses.map((e) => e.site_id ?? `p:${e.project_id}`)).size > 1 && (
              <Breakdown title="By site" total={shownTotal} data={bySite} active={site} onPick={(k) => setSite(site === k ? '' : k)} colour={(k) => k} swatchFor={(k) => swatch(expenses.find((e) => (e.site_id ?? `p:${e.project_id}`) === k)?.project_id ?? k)} />
            )}
          </aside>

          <div className="flex w-full min-w-0 flex-1 flex-col gap-3">
            {filtered && (
              <p className="flex items-center justify-between text-sm text-muted-foreground">
                <span>
                  {expenses.length} {expenses.length === 1 ? 'expense' : 'expenses'} · <span className="font-semibold text-foreground tabular-nums">{rupees(shownTotal)}</span>
                </span>
                <button type="button" className="text-xs font-semibold underline-offset-2 hover:underline" onClick={clearFilters}>
                  Clear filters
                </button>
              </p>
            )}
            {days.map((day) => (
              <section key={day.date} className="flex flex-col gap-1">
                <h3 className="flex items-baseline justify-between text-xs font-semibold text-muted-foreground">
                  <span>{dayLabel(day.date)}</span>
                  <span className="tabular-nums">{rupees(sum(day.rows))}</span>
                </h3>
                <ul className="divide-y overflow-hidden rounded-xl border">
                  {day.rows.map((e) => (
                    <li key={e.id} className="relative flex items-start gap-3 px-3 py-2.5 hover:bg-muted/30">
                      <span className={cn('mt-1 inline-flex size-8 shrink-0 items-center justify-center rounded-lg', VIA_TONE[e.paid_via].tone)} aria-hidden="true">
                        {React.createElement(VIA_ICON[e.paid_via], { className: 'size-4' })}
                      </span>
                      <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 text-left after:absolute after:inset-0" onClick={() => open(e)}>
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="font-medium">{e.vendor || e.category}</span>
                          {e.vendor && <span className="text-xs text-muted-foreground">{e.category}</span>}
                        </span>
                        <span className="line-clamp-1 text-xs text-muted-foreground">
                          {[e.number, e.site ?? e.project, e.description, e.source === 'whatsapp' ? 'WhatsApp' : null].filter(Boolean).join(' · ')}
                        </span>
                        <span className={cn(CHIP, 'mt-0.5 w-fit', PAID_VIA[e.paid_via].chip)}>{paidWords(e)}</span>
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
                            {canPay && (e.paid_via === 'unpaid' || e.paid_via === 'own_pocket' || e.payment === 'partially_paid') && (
                              <DropdownMenuItem
                                onClick={() => {
                                  setPayNow(true)
                                  open(e)
                                }}
                              >
                                {e.paid_via === 'own_pocket' ? `Repay ${(e.recorded_by ?? '').split(' ')[0] || 'who paid'}` : 'Mark paid'}
                              </DropdownMenuItem>
                            )}
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
                              !readOnly && <DropdownMenuItem onClick={() => open(e)}>Add bill</DropdownMenuItem>
                            )}
                            {e.vendor_id && <DropdownMenuItem onClick={() => setVendor(e.vendor_id!)}>Only {e.vendor}</DropdownMenuItem>}
                            {canPay && (
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
        </div>
      )}

      {!readOnly && (
        <Button className="fixed right-4 bottom-5 z-30 h-12 gap-2 rounded-full px-5 font-semibold shadow-lg md:hidden" onClick={() => setRecordOpen(true)}>
          <Plus className="size-5" strokeWidth={2.6} /> Expense
        </Button>
      )}

      <RecordExpenseDialog open={recordOpen} onOpenChange={setRecordOpen} scope={scope} onExpenseCreated={() => queryClient.invalidateQueries({ queryKey: ['finance'] })} />
      <ExpenseDetailSheet
        open={!!detail}
        onOpenChange={(o) => {
          if (!o) {
            close()
            setPayNow(false)
          }
        }}
        expense={detail}
        readOnly={readOnly}
        canPay={canPay}
        payNow={payNow}
        onOpenVendor={() => {
          if (opened?.vendor_id) setVendor(opened.vendor_id)
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
              It comes off the list and out of every total, and any payment recorded for it is reversed. To change an expense, take it back and record it
              again.
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

function Breakdown({
  title,
  total,
  data,
  active,
  onPick,
  colour,
  swatchFor,
}: {
  title: string
  total: number
  data: { top: { key: string; label: string; amount: number; n: number }[]; rest: number; restCount: number }
  active: string
  onPick: (key: string) => void
  colour: (key: string) => string
  swatchFor?: (key: string) => string
}) {
  const max = data.top[0]?.amount ?? 0
  return (
    <section className="flex flex-col gap-2 rounded-xl border bg-card p-3.5">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      <ul className="flex flex-col gap-1">
        {data.top.map((r) => {
          const on = active === r.key
          return (
            <li key={r.key}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onPick(r.key)}
                className={cn('flex w-full flex-col gap-1 rounded-lg px-2 py-1.5 text-left transition hover:bg-muted/50', on && 'bg-yellow-50 ring-1 ring-yellow-500 dark:bg-yellow-950')}
              >
                <span className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate font-medium">{r.label}</span>
                  <span className="shrink-0 tabular-nums">
                    <span className="font-semibold">{compact(r.amount)}</span>
                    <span className="ml-1.5 text-xs text-muted-foreground">{total > 0 ? Math.round((r.amount / total) * 100) : 0}%</span>
                  </span>
                </span>
                <span className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <span
                    className={cn('block h-full rounded-full', swatchFor ? '' : colour(r.key))}
                    style={{ width: `${max > 0 ? Math.max(4, (r.amount / max) * 100) : 0}%`, ...(swatchFor ? { background: swatchFor(r.key) } : {}) }}
                  />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {data.restCount > 0 && (
        <p className="px-2 text-xs text-muted-foreground">
          {data.restCount} more · {compact(data.rest)}
        </p>
      )}
    </section>
  )
}
