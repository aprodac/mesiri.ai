import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Gauge, Info, Tags } from 'lucide-react'
import { Callout, DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { PeriodSelect } from '@/components/filter-select'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { formatRupees, maySeeBoq } from '@/lib/boq'
import {
  CENTRE_COLOURS,
  fetchCentres,
  fetchCostCategories,
  mayManageMoney,
  setCategoryCentre,
  type CentreKey,
  type CostCategory,
} from '@/lib/cost'
import { compact } from '@/lib/expenses'
import { apiErrorMessage } from '@/lib/logo-upload'
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

const NOT_SET = '__not_set__'

function CategoryCentre({ category, centres, canEdit }: { category: CostCategory; centres: { key: CentreKey; label: string }[]; canEdit: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: (centre: CentreKey | null) => setCategoryCentre(category.id, centre),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cost'] })
      toast.success(`${category.name}: cost centre saved`)
    },
    onError: (err) => toast.error('Could not save the cost centre', apiErrorMessage(err)),
  })
  const label = centres.find((c) => c.key === category.cost_centre)?.label ?? 'Not set'
  return (
    <li className="flex items-center gap-3 px-3 py-2">
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{category.name}</span>
        {category.status !== 'active' && <span className="text-xs text-muted-foreground">Not in use</span>}
      </span>
      {canEdit ? (
        <Select
          value={category.cost_centre ?? NOT_SET}
          onValueChange={(v) => save.mutate(v === NOT_SET ? null : (v as CentreKey))}
          disabled={save.isPending}
        >
          <SelectTrigger className={cn('h-9 w-[170px]', !category.cost_centre && 'text-muted-foreground')} aria-label={`Cost centre of ${category.name}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NOT_SET}>Not set</SelectItem>
            {centres.map((c) => (
              <SelectItem key={c.key} value={c.key}>
                {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className={cn('text-sm', !category.cost_centre && 'text-muted-foreground')}>{label}</span>
      )}
    </li>
  )
}

export default function CostCentresPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const readOnly = useReadOnly()
  usePageTitle('Cost centres')
  const allowed = maySeeBoq(me?.role)
  const canEdit = mayManageMoney(me?.role) && !readOnly

  const [period, setPeriod] = useUrlState<Period>('period', '30d')
  const [from, setFrom] = useUrlState<string>('from', '')
  const [to, setTo] = useUrlState<string>('to', '')
  const range = periodRange(period, from, to)
  // "All" is the longest period the read model takes: two years.
  const twoYears = localIsoDate(new Date(Date.now() - 730 * 86400000))
  const filters = {
    date_from: range.from ?? (period === 'all' ? twoYears : undefined),
    date_to: range.to,
    project_id: scope.mode !== 'portfolio' ? scope.projectId : undefined,
    site_id: scope.mode === 'site' ? scope.siteId : undefined,
  }
  const data = useQuery({ queryKey: ['cost', 'centres', filters], queryFn: () => fetchCentres(filters), enabled: allowed })
  const cats = useQuery({ queryKey: ['cost', 'categories'], queryFn: fetchCostCategories, enabled: allowed })

  if (!allowed) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">Cost control shows the company's spending.</p>
        <p className="text-sm text-muted-foreground">Only owners, admins, finance and project managers can open it.</p>
      </div>
    )
  }
  if (data.isError) return <PageError message="Cost centres could not be loaded." onRetry={() => data.refetch()} back={{ to: '/today', label: 'Today' }} />

  const d = data.data
  const total = Number(d?.total ?? 0)
  const rows = d ? [...d.centres.map((c) => ({ ...c, colour: CENTRE_COLOURS[c.key] }))] : []
  const notSet = Number(d?.not_set.amount ?? 0)
  const notes = [
    d && d.unpriced_deliveries > 0 ? `${d.unpriced_deliveries} ${d.unpriced_deliveries === 1 ? 'delivery has' : 'deliveries have'} no price, so ${d.unpriced_deliveries === 1 ? 'it is' : 'they are'} not in Materials` : null,
    d && Number(d.man_days) > Number(d.priced_man_days)
      ? `${Number(d.man_days) - Number(d.priced_man_days)} of ${d.man_days} man-days have no wage, so they are not in Labour`
      : null,
    // D-CC8: cost is before GST that can be claimed back; GST that cannot is in the cost, and said.
    d?.gst && Number(d.gst.claimable) > 0 ? `${formatRupees(d.gst.claimable)} of GST is left out of cost: it can be claimed back (the supplier has a GSTIN)` : null,
    d?.gst && Number(d.gst.in_cost) > 0
      ? `${formatRupees(d.gst.in_cost)} of GST on ${d.gst.in_cost_count} ${d.gst.in_cost_count === 1 ? 'expense is' : 'expenses is'} counted as cost: no GSTIN on the supplier, or not said as included`
      : null,
  ].filter(Boolean) as string[]
  const unset = (cats.data?.categories ?? []).filter((c) => !c.cost_centre && c.status === 'active')

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/cost', label: 'Overview' }}
        crumb="Cost control"
        title="Cost centres"
        date={scope.mode === 'portfolio' ? 'All projects' : scope.mode === 'site' ? `${scope.projectName} · ${scope.siteName}` : scope.projectName}
        action={<PeriodSelect value={period} onChange={setPeriod} from={from} to={to} onFrom={setFrom} onTo={setTo} />}
      />

      <section aria-label="Total" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Spent in this period</p>
            <p className="text-3xl font-semibold tabular-nums">{data.isLoading ? '–' : compact(total)}</p>
          </div>
          {d && (
            <p className="text-xs text-muted-foreground">
              {d.date_from} to {d.date_to} · the same total as Expenses › Full cost
            </p>
          )}
        </div>
        <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          {rows.map((c) => (
            <span key={c.key} className={c.colour} style={{ width: `${total > 0 ? (Number(c.amount) / total) * 100 : 0}%` }} />
          ))}
          <span className={CENTRE_COLOURS.not_set} style={{ width: `${total > 0 ? (notSet / total) * 100 : 0}%` }} />
        </div>
        {notes.map((n) => (
          <p key={n} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Info className="size-3.5" /> {n}
          </p>
        ))}
      </section>

      {notSet > 0 && (
        <Callout tone="muted" icon={Tags}>
          {compact(notSet)} of expenses are in categories with no cost centre: {d?.not_set.parts.map((p) => p.source.replace('Expenses: ', '')).join(', ')}.{' '}
          {canEdit ? 'Pick a centre for each below; the figures move at once.' : 'The owner, an admin or finance can pick a centre for each.'}
        </Callout>
      )}

      <DprSection icon={Gauge} title="Where the money went">
        {data.isLoading ? (
          <Skeleton className="h-48 rounded-lg" />
        ) : (
          <ul className="divide-y rounded-lg border text-sm">
            {[...rows, ...(notSet > 0 ? [{ key: 'not_set' as const, label: 'Not set', amount: d!.not_set.amount, parts: d!.not_set.parts, colour: CENTRE_COLOURS.not_set }] : [])].map((c) => {
              const amount = Number(c.amount)
              return (
                <li key={c.key} className="flex flex-col gap-1.5 px-3 py-3">
                  <div className="flex items-center gap-3">
                    <span className={cn('size-2.5 shrink-0 rounded-full', c.colour)} />
                    <span className={cn('flex-1 font-medium', amount === 0 && 'text-muted-foreground')}>{c.label}</span>
                    <span className="text-xs text-muted-foreground tabular-nums">{total > 0 && amount > 0 ? `${Math.round((amount / total) * 100)}%` : ''}</span>
                    <span className={cn('w-24 text-right font-semibold tabular-nums', amount === 0 && 'font-normal text-muted-foreground')}>
                      {amount === 0 ? '—' : compact(amount)}
                    </span>
                  </div>
                  {c.parts.length > 0 && (
                    <ul className="ml-5 flex flex-col gap-0.5 text-xs text-muted-foreground">
                      {c.parts.map((p) => (
                        <li key={`${p.source}-${p.category_id ?? ''}`} className="flex justify-between gap-3">
                          <span className="truncate">
                            {p.source}
                            {p.count ? ` · ${p.count}` : ''}
                            {p.man_days ? ` · ${p.man_days} man-days` : ''}
                          </span>
                          <span className="tabular-nums">{compact(Number(p.amount))}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </DprSection>

      <DprSection icon={Tags} title="Expense categories and their cost centre" meta={unset.length ? `${unset.length} not set` : undefined}>
        <p className="mb-2 text-sm text-muted-foreground">
          Deliveries, attendance and machines go to their centre by themselves. An expense counts in the centre of its category; a subcontract
          bill is always Subcontract. Categories are added on <Link to="/finance/expenses" className="underline underline-offset-2">Expenses</Link>.
        </p>
        {cats.isLoading ? (
          <Skeleton className="h-32 rounded-lg" />
        ) : (
          <ul className="divide-y rounded-lg border text-sm">
            {(cats.data?.categories ?? []).map((c) => (
              <CategoryCentre key={c.id} category={c} centres={cats.data?.centres ?? []} canEdit={canEdit} />
            ))}
          </ul>
        )}
      </DprSection>
    </div>
  )
}
