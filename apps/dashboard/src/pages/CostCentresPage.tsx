import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDownWideNarrow, ArrowRight, Boxes, ChevronDown, ChevronUp, Fuel, Gauge, Handshake, HardHat, Landmark, PackageX, Receipt,
  Search, Shapes, Tags, Truck, Wallet, X,
} from 'lucide-react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import { ActionButton, NoAccess } from '@/components/page/page-kit'
import { Pager } from '@/components/page/pager'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { PeriodSelect } from '@/components/filter-select'
import { FilterPill, type FilterOption } from '@/components/requests/parts'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { formatRupees, maySeeBoq } from '@/lib/boq'
import { appNow } from '@/lib/clock'
import {
  CENTRE_COLOURS, fetchCentres, fetchCostCategories, mayManageMoney, setCategoryCentre, type CentreKey, type CentrePart, type CostCategory,
  type CostCentres,
} from '@/lib/cost'
import { compact } from '@/lib/expenses'
import { exportCsv } from '@/lib/export'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePagedUrl } from '@/lib/paging'
import { usePageTitle } from '@/lib/page-title'
import { periodRange, type Period } from '@/lib/period'
import { useScope } from '@/lib/ScopeContext'
import { localIsoDate } from '@/lib/site-day'
import { useReadOnly } from '@/lib/trial'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// CC-01: where a period's money went, in cost centres. Every figure is the Expenses page's Full cost (one read model,
// backend domains/costing/centres.py), with the expenses split by their category's centre. Expenses whose category
// has no centre are "Not set" and say which categories to fix; picking a centre here moves them.
// UX-41 (18 Nov, "work on cost centres"): it reads by colour. The total with its change against the period before and
// one bar of the centres, each named in its colour; a card per centre (icon, amount, share, change, what it is made
// of, each part a link to its page); the notes as chips; the categories as a table with what each spent, search,
// filter, sort, pages, and several set to a centre at once.

const NOT_SET = '__not_set__'
type Key = CentreKey | 'not_set'

/** Each centre's icon and soft tile, in its colour (lib/cost.ts CENTRE_COLOURS). */
const CENTRE_LOOK: Record<Key, { icon: LucideIcon; tile: string }> = {
  materials: { icon: Boxes, tile: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400' },
  labour: { icon: HardHat, tile: 'bg-amber-500/15 text-amber-700 dark:text-amber-400' },
  subcontract: { icon: Handshake, tile: 'bg-violet-500/15 text-violet-700 dark:text-violet-400' },
  equipment: { icon: Truck, tile: 'bg-teal-500/15 text-teal-700 dark:text-teal-400' },
  fuel: { icon: Fuel, tile: 'bg-orange-500/15 text-orange-700 dark:text-orange-400' },
  overhead: { icon: Landmark, tile: 'bg-sky-500/15 text-sky-700 dark:text-sky-400' },
  other: { icon: Shapes, tile: 'bg-slate-500/15 text-slate-600 dark:text-slate-300' },
  not_set: { icon: Tags, tile: 'bg-muted text-muted-foreground' },
}

/** Where a part of a centre lives in the app, so its figure can be opened. */
function partLink(p: CentrePart): string | null {
  if (p.category_id) return `/finance/expenses?category=${p.category_id}`
  const s = p.source.toLowerCase()
  if (s.includes('labour') || s.includes('attendance') || s.includes('wage')) return '/labour'
  if (s.includes('deliver') || s.includes('material')) return '/materials?view=movements&dir=in'
  if (s.includes('machine') || s.includes('hire') || s.includes('diesel') || s.includes('fuel')) return '/equipment'
  if (s.includes('subcontract') || s.includes('work order')) return '/subcontract/bills'
  return null
}
const partName = (p: CentrePart) => p.source.replace(/^Expenses: /, '')
const shortDay = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** ▲ / ▼ against the period before: up is red (more spent), down green. */
function Change({ now, then, label = 'vs before' }: { now: number; then: number | null; label?: string }) {
  if (then === null) return null
  const d = now - then
  if (Math.abs(d) < 0.5) return <span className="text-[11px] text-muted-foreground">same as before</span>
  return (
    <span className={cn('text-[11px] font-medium tabular-nums', d > 0 ? 'text-destructive' : 'text-success')}>
      {d > 0 ? '▲' : '▼'} {compact(Math.abs(d))} <span className="font-normal text-muted-foreground">{label}</span>
    </span>
  )
}

function CentreCard({ k, label, amount, parts, total, then }: { k: Key; label: string; amount: number; parts: CentrePart[]; total: number; then: number | null }) {
  const [all, setAll] = React.useState(false)
  const look = CENTRE_LOOK[k]
  const share = total > 0 ? amount / total : 0
  const sorted = [...parts].sort((a, b) => Number(b.amount) - Number(a.amount))
  const shown = all ? sorted : sorted.slice(0, 3)
  return (
    <div className={cn('flex flex-col gap-2.5 rounded-xl border bg-card p-3.5', amount === 0 && 'opacity-60', k === 'not_set' && 'border-dashed')}>
      <div className="flex items-center gap-2">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-lg', look.tile)} aria-hidden>
          <look.icon className="size-4" />
        </span>
        <span className="min-w-0 flex-1 truncate font-semibold">{label}</span>
        <span className="text-xs font-semibold text-muted-foreground tabular-nums">{amount > 0 ? `${Math.round(share * 100)}%` : ''}</span>
      </div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xl font-semibold tabular-nums">{amount === 0 ? '—' : compact(amount)}</span>
        <Change now={amount} then={then} />
      </div>
      <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', CENTRE_COLOURS[k])} style={{ width: `${Math.max(share * 100, amount > 0 ? 2 : 0)}%` }} />
      </span>
      {sorted.length > 0 && (
        <ul className="flex flex-col gap-0.5 border-t pt-2 text-xs">
          {shown.map((p) => {
            const to = partLink(p)
            const body = (
              <>
                <span className="min-w-0 truncate">
                  {partName(p)}
                  {p.count ? <span className="text-muted-foreground"> · {p.count}</span> : null}
                  {p.man_days ? <span className="text-muted-foreground"> · {p.man_days} md</span> : null}
                </span>
                <span className="shrink-0 font-medium tabular-nums">{compact(Number(p.amount))}</span>
              </>
            )
            return (
              <li key={`${p.source}-${p.category_id ?? ''}`}>
                {to ? (
                  <Link to={to} className="-mx-1 flex justify-between gap-3 rounded px-1 py-0.5 hover:bg-muted/60">
                    {body}
                  </Link>
                ) : (
                  <span className="flex justify-between gap-3 py-0.5">{body}</span>
                )}
              </li>
            )
          })}
          {sorted.length > 3 && (
            <li>
              <button type="button" className="mt-0.5 inline-flex items-center gap-0.5 text-[11px] font-semibold text-muted-foreground hover:text-foreground" onClick={() => setAll(!all)}>
                {all ? (
                  <>
                    Fewer <ChevronUp className="size-3" />
                  </>
                ) : (
                  <>
                    {sorted.length - 3} more <ChevronDown className="size-3" />
                  </>
                )}
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

/** A note about what the figures leave out, as a chip; a link when it can be fixed. */
function Note({ icon: Icon, tone, children, to }: { icon: LucideIcon; tone: 'attention' | 'muted'; children: React.ReactNode; to?: string }) {
  const cls = cn(
    'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs',
    tone === 'attention' ? 'bg-draft-soft text-draft' : 'border bg-card text-muted-foreground',
    to && 'hover:ring-1 hover:ring-foreground/20',
  )
  const body = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
      {to && <ArrowRight className="size-3" aria-hidden />}
    </>
  )
  if (!to) return <span className={cls}>{body}</span>
  return to.startsWith('#') ? <a href={to} className={cls}>{body}</a> : <Link to={to} className={cls}>{body}</Link>
}

function CentrePick({ category, centres, canEdit, onSave, saving }: { category: CostCategory; centres: { key: CentreKey; label: string }[]; canEdit: boolean; onSave: (c: CentreKey | null) => void; saving: boolean }) {
  const key: Key = category.cost_centre ?? 'not_set'
  const label = centres.find((c) => c.key === category.cost_centre)?.label ?? 'Not set'
  const mark = <span className={cn('size-2 shrink-0 rounded-full', CENTRE_COLOURS[key])} aria-hidden />
  if (!canEdit) {
    return (
      <span className={cn('inline-flex items-center gap-1.5 text-sm', !category.cost_centre && 'text-draft')}>
        {mark} {label}
      </span>
    )
  }
  return (
    <Select value={category.cost_centre ?? NOT_SET} onValueChange={(v) => onSave(v === NOT_SET ? null : (v as CentreKey))} disabled={saving}>
      <SelectTrigger className={cn('h-8 w-[128px] gap-2 bg-card sm:w-[170px]', !category.cost_centre && 'border-draft/50 text-draft')} aria-label={`Cost centre of ${category.name}`}>
        <span className="flex items-center gap-2">
          {mark}
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NOT_SET}>Not set</SelectItem>
        {centres.map((c) => (
          <SelectItem key={c.key} value={c.key}>
            <span className="flex items-center gap-2">
              <span className={cn('size-2 rounded-full', CENTRE_COLOURS[c.key])} aria-hidden />
              {c.label}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

const CAT_SORTS = [
  { value: '', label: 'Most spent' },
  { value: 'name', label: 'Name' },
  { value: 'centre', label: 'Cost centre' },
]

export default function CostCentresPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const readOnly = useReadOnly()
  const toast = useToast()
  const qc = useQueryClient()
  usePageTitle('Cost centres')
  const allowed = maySeeBoq(me?.role)
  const canEdit = mayManageMoney(me?.role) && !readOnly

  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const [q, setQ] = useUrlState<string>('q', '')
  const [centreFilter, setCentreFilter] = useUrlState<string>('centre', '')
  const [catSort, setCatSort] = useUrlState<string>('sort', '')
  const [picked, setPicked] = React.useState<Set<string>>(new Set())
  const range = periodRange(period, from, to)
  // "All" is the longest period the read model takes: two years.
  const today = appNow()
  const twoYears = localIsoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 730))
  const scoped = {
    project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    site_id: scope.mode === 'site' ? scope.siteId : undefined,
  }
  const filters = { ...scoped, date_from: range.from ?? (period === 'all' ? twoYears : undefined), date_to: range.to }
  const data = useQuery({ queryKey: ['cost', 'centres', filters], queryFn: () => fetchCentres(filters), enabled: allowed })
  // The same number of days just before, for "▲ ₹x vs before" (not for "everything").
  const prevFilters = React.useMemo(() => {
    if (period === 'all' || !data.data) return null
    const f = new Date(`${data.data.date_from}T00:00:00`)
    const t = new Date(`${data.data.date_to}T00:00:00`)
    const span = Math.round((t.getTime() - f.getTime()) / 86_400_000) + 1
    if (!(span > 0) || span > 366) return null
    const shift = (d: Date, n: number) => localIsoDate(new Date(d.getFullYear(), d.getMonth(), d.getDate() - n))
    return { ...scoped, date_from: shift(f, span), date_to: shift(f, 1) }
  }, [period, data.data, scoped.project_id, scoped.site_id]) // eslint-disable-line react-hooks/exhaustive-deps
  const prev = useQuery({ queryKey: ['cost', 'centres', prevFilters], queryFn: () => fetchCentres(prevFilters!), enabled: allowed && !!prevFilters, retry: false })
  const cats = useQuery({ queryKey: ['cost', 'categories'], queryFn: fetchCostCategories, enabled: allowed })

  const save = useMutation({
    mutationFn: async ({ ids, centre }: { ids: string[]; centre: CentreKey | null }) => {
      for (const id of ids) await setCategoryCentre(id, centre)
      return ids.length
    },
    onSuccess: (n, { centre }) => {
      qc.invalidateQueries({ queryKey: ['cost'] })
      setPicked(new Set())
      const word = cats.data?.centres.find((c) => c.key === centre)?.label ?? 'Not set'
      toast.success(n === 1 ? `Cost centre saved: ${word}` : `${n} categories moved to ${word}`)
    },
    onError: (err) => toast.error('Could not save the cost centre', apiErrorMessage(err)),
  })

  // What each expense category spent in the period, from the centres' parts.
  const spentBy = React.useMemo(() => {
    const m = new Map<string, number>()
    const d = data.data
    if (!d) return m
    for (const part of [...d.centres.flatMap((c) => c.parts), ...d.not_set.parts]) {
      if (part.category_id) m.set(part.category_id, (m.get(part.category_id) ?? 0) + Number(part.amount))
    }
    return m
  }, [data.data])
  const categories = React.useMemo(() => cats.data?.categories ?? [], [cats.data])
  const needle = q.trim().toLowerCase()
  const listed = React.useMemo(() => {
    const out = categories.filter(
      (c) =>
        (!centreFilter || (centreFilter === 'not_set' ? !c.cost_centre : c.cost_centre === centreFilter)) &&
        (!needle || `${c.name} ${c.code ?? ''}`.toLowerCase().includes(needle)),
    )
    const centreOrder = (c: CostCategory) => (c.cost_centre ? (cats.data?.centres.findIndex((x) => x.key === c.cost_centre) ?? 0) : -1)
    return out.sort((a, b) =>
      catSort === 'name' ? a.name.localeCompare(b.name)
      : catSort === 'centre' ? centreOrder(a) - centreOrder(b) || a.name.localeCompare(b.name)
      : (spentBy.get(b.id) ?? 0) - (spentBy.get(a.id) ?? 0) || a.name.localeCompare(b.name),
    )
  }, [categories, centreFilter, needle, catSort, spentBy, cats.data])
  const paged = usePagedUrl(listed)

  if (!allowed) return <NoAccess roles={MONEY_PEOPLE} />
  if (data.isError) return <PageError message="Cost centres could not be loaded." onRetry={() => data.refetch()} back={{ to: '/today', label: 'Today' }} />

  const d = data.data
  const total = Number(d?.total ?? 0)
  const notSet = Number(d?.not_set.amount ?? 0)
  const prevAmount = (p: CostCentres | undefined, k: Key) =>
    !p ? null : k === 'not_set' ? Number(p.not_set.amount) : Number(p.centres.find((c) => c.key === k)?.amount ?? 0)
  const cards: { k: Key; label: string; amount: number; parts: CentrePart[] }[] = d
    ? [
        ...d.centres.map((c) => ({ k: c.key as Key, label: c.label, amount: Number(c.amount), parts: c.parts })),
        ...(notSet > 0 ? [{ k: 'not_set' as Key, label: 'Not set', amount: notSet, parts: d.not_set.parts }] : []),
      ]
        .filter((c) => c.amount > 0)
        .sort((a, b) => b.amount - a.amount)
    : []
  const unset = categories.filter((c) => !c.cost_centre && c.status === 'active')
  const centreOptions: FilterOption[] = [
    { value: 'not_set', label: 'Not set', dot: CENTRE_COLOURS.not_set, count: categories.filter((c) => !c.cost_centre).length },
    ...(cats.data?.centres ?? []).map((c) => ({ value: c.key, label: c.label, dot: CENTRE_COLOURS[c.key], count: categories.filter((x) => x.cost_centre === c.key).length })),
  ]
  const allOnPage = paged.shown.length > 0 && paged.shown.every((c) => picked.has(c.id))
  const toggle = (id: string) =>
    setPicked((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const exportCats = () =>
    exportCsv(
      `cost-centres-${d?.date_from ?? ''}-to-${d?.date_to ?? ''}.csv`,
      ['Category', 'Code', 'Cost centre', 'Spent in the period', 'In use'],
      listed.map((c) => [c.name, c.code ?? '', cats.data?.centres.find((x) => x.key === c.cost_centre)?.label ?? 'Not set', spentBy.get(c.id) ?? 0, c.status === 'active' ? 'yes' : 'no']),
    )

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <DprHeader
        back={{ to: '/cost', label: 'Overview' }}
        crumb="Cost control"
        title="Cost centres"
        date={d ? `${shortDay(d.date_from)} – ${shortDay(d.date_to)}` : undefined}
        action={<span data-guide="centres.period"><PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} /></span>}
      />

      {/* The total and one bar of the centres, each named in its colour. */}
      <section aria-label="Total" className="flex flex-col gap-3 rounded-xl border bg-card p-4" data-guide="centres.total">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div className="flex flex-col">
            <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Wallet className="size-3.5" aria-hidden /> Spent
            </span>
            <span className="text-3xl font-semibold tabular-nums">{data.isLoading ? '–' : compact(total)}</span>
            {d && <Change now={total} then={prev.data ? Number(prev.data.total) : null} label="vs the days before" />}
          </div>
          <span className="text-xs text-muted-foreground">Same total as Expenses › Full cost</span>
        </div>
        <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={cards.map((c) => `${c.label} ${compact(c.amount)}`).join(', ')}>
          {cards.map((c) => c.amount > 0 && <span key={c.k} className={CENTRE_COLOURS[c.k]} style={{ width: `${total > 0 ? (c.amount / total) * 100 : 0}%` }} title={`${c.label}: ${compact(c.amount)}`} />)}
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {cards.filter((c) => c.amount > 0).map((c) => (
            <li key={c.k} className="flex items-center gap-1.5">
              <span className={cn('size-2 rounded-full', CENTRE_COLOURS[c.k])} aria-hidden />
              {c.label} <span className="font-semibold tabular-nums">{Math.round((c.amount / Math.max(total, 1)) * 100)}%</span>
            </li>
          ))}
        </ul>
        {d && (
          <div className="flex flex-wrap gap-1.5">
            {notSet > 0 && (
              <Note icon={Tags} tone="attention" to="#categories">
                <b className="tabular-nums">{compact(notSet)}</b> in {unset.length || 'some'} {unset.length === 1 ? 'category' : 'categories'} with no centre
              </Note>
            )}
            {d.unpriced_deliveries > 0 && (
              <Note icon={PackageX} tone="attention" to="/materials?view=movements&dir=in">
                <b className="tabular-nums">{d.unpriced_deliveries}</b> {d.unpriced_deliveries === 1 ? 'delivery' : 'deliveries'} with no price, not in Materials
              </Note>
            )}
            {Number(d.man_days) > Number(d.priced_man_days) && (
              <Note icon={HardHat} tone="attention" to="/labour">
                <b className="tabular-nums">{Number(d.man_days) - Number(d.priced_man_days)}</b> man-days with no wage, not in Labour
              </Note>
            )}
            {d.gst && Number(d.gst.claimable) > 0 && (
              <Note icon={Receipt} tone="muted">
                <b className="tabular-nums">{formatRupees(d.gst.claimable)}</b> GST left out: it can be claimed back
              </Note>
            )}
            {d.gst && Number(d.gst.in_cost) > 0 && (
              <Note icon={Receipt} tone="muted">
                <b className="tabular-nums">{formatRupees(d.gst.in_cost)}</b> GST counted as cost ({d.gst.in_cost_count} {d.gst.in_cost_count === 1 ? 'expense' : 'expenses'}, no GSTIN)
              </Note>
            )}
          </div>
        )}
      </section>

      <div data-guide="centres.list">
        <DprSection icon={Gauge} title="Where the money went" meta={cards.length || undefined}>
          {data.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-40 rounded-xl" />
              ))}
            </div>
          ) : (
            cards.length === 0 ? (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
                <Wallet className="size-5 text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">Nothing spent in these days</p>
              </div>
            ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {cards.map((c) => (
                <CentreCard key={c.k} k={c.k} label={c.label} amount={c.amount} parts={c.parts} total={total} then={prevAmount(prev.data, c.k)} />
              ))}
            </div>
            )
          )}
        </DprSection>
      </div>

      <div data-guide="centres.categories" id="categories" className="scroll-mt-20">
        <DprSection icon={Tags} title="Expense categories" meta={unset.length ? <span className="text-draft">{unset.length} not set</span> : categories.length || undefined}>
          {cats.isLoading ? (
            <Skeleton className="h-32 rounded-xl" />
          ) : (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <label className="flex h-9 items-center gap-2 rounded-lg border bg-card px-2.5">
                  <Search className="size-4 text-muted-foreground" aria-hidden />
                  <span className="sr-only">Search categories</span>
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search categories" className="w-36 bg-transparent text-sm outline-none sm:w-44" />
                </label>
                <FilterPill icon={Tags} label="Cost centre" allLabel="Any centre" value={centreFilter} options={centreOptions} onChange={setCentreFilter} />
                {(q || centreFilter) && (
                  <Button variant="ghost" size="sm" className="h-9 gap-1" onClick={() => { setQ(''); setCentreFilter('') }}>
                    <X className="size-3.5" aria-hidden /> Clear
                  </Button>
                )}
                <span className="ml-auto flex items-center gap-2">
                  <label className="flex h-9 items-center gap-1.5 rounded-lg border bg-card px-2.5 text-sm">
                    <ArrowDownWideNarrow className="size-4 text-muted-foreground" aria-hidden />
                    <select value={catSort} onChange={(e) => setCatSort(e.target.value)} className="bg-transparent outline-none" aria-label="Sort the categories">
                      {CAT_SORTS.map((x) => (
                        <option key={x.value} value={x.value}>
                          {x.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <ActionButton kind="export-excel" size="default" disabled={listed.length === 0} onClick={exportCats} title="The categories shown, as a CSV file (opens in Excel)">
                    <span className="hidden sm:inline">Export</span>
                  </ActionButton>
                </span>
              </div>

              {/* Several at once: tick them, pick the centre. */}
              {canEdit && picked.size > 0 && (
                <div className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-foreground/20 bg-foreground px-3 py-2 text-sm text-background">
                  <span className="font-semibold tabular-nums">{picked.size} picked</span>
                  <span className="opacity-70">Move to</span>
                  <Select onValueChange={(v) => save.mutate({ ids: [...picked], centre: v === NOT_SET ? null : (v as CentreKey) })} disabled={save.isPending}>
                    <SelectTrigger className="h-8 w-[170px] bg-background text-foreground" aria-label="Cost centre for the picked categories">
                      <SelectValue placeholder={save.isPending ? 'Saving…' : 'Pick a centre'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(cats.data?.centres ?? []).map((c) => (
                        <SelectItem key={c.key} value={c.key}>
                          <span className="flex items-center gap-2">
                            <span className={cn('size-2 rounded-full', CENTRE_COLOURS[c.key])} aria-hidden />
                            {c.label}
                          </span>
                        </SelectItem>
                      ))}
                      <SelectItem value={NOT_SET}>Not set</SelectItem>
                    </SelectContent>
                  </Select>
                  <button type="button" className="ml-auto inline-flex items-center gap-1 text-xs opacity-80 hover:opacity-100" onClick={() => setPicked(new Set())}>
                    <X className="size-3.5" aria-hidden /> Clear
                  </button>
                </div>
              )}

              {listed.length === 0 ? (
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-10 text-center">
                  <Search className="size-5 text-muted-foreground" aria-hidden />
                  <p className="text-sm font-medium">No category matches</p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border bg-card [contain:inline-size]">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 text-xs text-muted-foreground">
                      <tr>
                        {canEdit && (
                          <th className="w-9 py-2 pl-3">
                            <input
                              type="checkbox"
                              className="size-4 accent-foreground"
                              aria-label="Pick every category on this page"
                              checked={allOnPage}
                              onChange={() =>
                                setPicked((s) => {
                                  const n = new Set(s)
                                  for (const c of paged.shown) {
                                    if (allOnPage) n.delete(c.id)
                                    else n.add(c.id)
                                  }
                                  return n
                                })
                              }
                            />
                          </th>
                        )}
                        <th className="px-3 py-2 text-left font-medium">Category</th>
                        <th className="px-3 py-2 text-right font-medium">Spent</th>
                        <th className="px-3 py-2 text-left font-medium">Cost centre</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {paged.shown.map((c) => {
                        const spent = spentBy.get(c.id) ?? 0
                        return (
                          <tr key={c.id} className={cn('hover:bg-muted/30', !c.cost_centre && c.status === 'active' && 'bg-draft-soft/40', picked.has(c.id) && 'bg-muted/60')}>
                            {canEdit && (
                              <td className="py-2 pl-3">
                                <input type="checkbox" className="size-4 accent-foreground" aria-label={`Pick ${c.name}`} checked={picked.has(c.id)} onChange={() => toggle(c.id)} />
                              </td>
                            )}
                            <td className="px-3 py-2">
                              <span className="flex items-center gap-2">
                                <span className={cn('font-medium', c.status !== 'active' && 'text-muted-foreground')}>{c.name}</span>
                                {c.status !== 'active' && <span className="rounded bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">Not in use</span>}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {spent > 0 ? (
                                <Link to={`/finance/expenses?category=${c.id}`} className="font-medium hover:underline">
                                  {compact(spent)}
                                </Link>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5">
                              <CentrePick
                                category={c}
                                centres={cats.data?.centres ?? []}
                                canEdit={canEdit}
                                saving={save.isPending}
                                onSave={(centre) => save.mutate({ ids: [c.id], centre })}
                              />
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <Pager {...paged.pager} noun="categories" className="mt-2" />
              {!canEdit && unset.length > 0 && <p className="mt-2 text-xs text-muted-foreground">The owner, an admin or finance can pick a centre for each.</p>}
            </>
          )}
        </DprSection>
      </div>
    </div>
  )
}
