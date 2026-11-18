import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  CircleCheck, CircleDashed, ClipboardList, Eye, Package, PackageCheck, PackageSearch, PackageX, TriangleAlert,
} from 'lucide-react'
import { MONEY_PEOPLE } from '@/lib/permissions'
import {
  ActionButton, ActionChip, ClearButton, KpiStrip, Legend, NoAccess, NoMatch, Pill, ReasonChip, SearchBox, SortSelect, StateBar, ToggleChip,
} from '@/components/page/page-kit'
import { Pager } from '@/components/page/pager'
import { NumbersTable, ShowSwitch, type NumberColumn } from '@/components/page/numbers-view'
import { sortByColumn, useColumnSort, useShowMode } from '@/lib/numbers-view'
import { DprHeader, DprSection, PageError } from '@/components/dpr-page'
import { ProjectPickList } from '@/components/schedule/project-picker'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/lib/AuthContext'
import { formatQuantity, maySeeBoq } from '@/lib/boq'
import { fetchProjectMaterials, type MaterialReconciliation, type VarianceColour } from '@/lib/cost'
import { COLOUR_DOT, COLOUR_TEXT, COLOUR_TONE, COLOUR_WORD } from '@/lib/cost-colours'
import { exportCsv } from '@/lib/export'
import { usePagedUrl } from '@/lib/paging'
import { usePageTitle } from '@/lib/page-title'
import { useScope } from '@/lib/ScopeContext'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// CC-08: materials against the BOQ. Per material with a norm on a BOQ line (MP-01): what the work done so far should
// have used against what was used, and what is still needed to finish against what is on hand and coming, so a
// shortage is seen before closeout ("4 loads of metal short"). Backend: GET /cost/projects/{id}/materials.
// UX-42 (18 Nov): it reads by colour and shape. A KPI strip; one bar of the materials by colour whose chips filter, and
// "short to finish" as a filter; each material its use against what the work needed as a bar with a tick at the need,
// what is still needed to finish as one bar (on hand green, on order blue, short red), a short reason chip with its
// fix, and a link to its stock book; search, sort, pages and export.
// UX-43: a Bars / Numbers switch; Numbers puts every figure in its own column, any header sorts (UX-44: the shared
// components/page/numbers-view.tsx).

type M = MaterialReconciliation
const n = (v: string | null | undefined) => (v === null || v === undefined ? 0 : Number(v))

/** Each colour's icon; its look is the list kit's tone (COLOUR_TONE). */
const LOOK: Record<VarianceColour, { icon: LucideIcon }> = { red: { icon: TriangleAlert }, amber: { icon: Eye }, green: { icon: CircleCheck }, grey: { icon: CircleDashed } }
const ORDER: VarianceColour[] = ['red', 'amber', 'green', 'grey']

/** Why a material is its colour, in a few words (the full sentence is its tooltip). */
const REASON: Record<M['reason'], string> = {
  over_norm: 'Used more than the work needed',
  near_norm: 'A little more, within 10%',
  within_norm: 'Within what the work needed',
  used_no_work: 'Used, no work measured',
  no_usage_recorded: 'No use recorded on site',
  nothing_yet: 'Nothing used yet',
  unit_differs: 'Stock in another unit',
}

function why(m: M): string {
  const u = m.unit
  switch (m.reason) {
    case 'over_norm':
    case 'near_norm':
      return `${formatQuantity(m.used)} ${u} used; the work done needed ${formatQuantity(m.should_have_used)} ${u}: ${formatQuantity(m.used_over_work ?? '0')} ${u} more than the work accounts for.`
    case 'within_norm':
      return `${formatQuantity(m.used)} ${u} used; the work done needed ${formatQuantity(m.should_have_used)} ${u}.`
    case 'used_no_work':
      return `${formatQuantity(m.used)} ${u} used and no work measured on the lines that use it.`
    case 'no_usage_recorded':
      return `The work done needed ${formatQuantity(m.should_have_used)} ${u}, but no use of it is recorded on site.`
    case 'nothing_yet':
      return 'No work on its lines and nothing used yet.'
    case 'unit_differs':
      return `The stock is kept in ${m.stock_unit} and the BOQ norm in ${u}, so they are not compared.`
  }
}

/** Used against what the work done needed: a bar in its colour, a tick where the need ends. */
function UsedBar({ m }: { m: M }) {
  const used = n(m.used)
  const need = n(m.should_have_used)
  const scale = Math.max(used, need)
  if (scale <= 0 || m.reason === 'unit_differs') return <span className="text-xs text-muted-foreground">—</span>
  const pct = (v: number) => Math.min(100, (v / scale) * 100)
  return (
    <span className="flex flex-col gap-1">
      <span className="relative block h-2 rounded-full bg-muted" aria-hidden>
        <span className={cn('block h-full rounded-full', COLOUR_DOT[m.colour])} style={{ width: `${Math.max(pct(used), used > 0 ? 2 : 0)}%` }} />
        {need > 0 && <span className="absolute -top-1 -bottom-1 w-0.5 rounded bg-foreground/70" style={{ left: `calc(${pct(need)}% - 1px)` }} title={`The work needed ${formatQuantity(m.should_have_used)} ${m.unit}`} />}
      </span>
      <span className="flex justify-between text-[11px] tabular-nums">
        <span>
          <span className={cn('font-semibold', COLOUR_TEXT[m.colour])}>{formatQuantity(m.used)}</span> <span className="text-muted-foreground">used</span>
        </span>
        <span className="text-muted-foreground">
          {formatQuantity(m.should_have_used)} needed
        </span>
      </span>
    </span>
  )
}

/** What is still needed to finish, as one bar: on hand (green), on order (blue), short (red). */
function FinishBar({ m }: { m: M }) {
  const still = n(m.still_needed)
  if (m.short_by === null) return <span className="text-xs text-muted-foreground">—</span>
  if (still <= 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
        <PackageCheck className="size-3.5" aria-hidden /> Nothing left to need
      </span>
    )
  }
  const hand = Math.min(n(m.on_hand), still)
  const order = Math.min(n(m.on_order), Math.max(0, still - hand))
  const short = Math.max(0, n(m.short_by))
  const total = Math.max(still, hand + order + short)
  const w = (v: number) => `${(v / total) * 100}%`
  return (
    <span className="flex flex-col gap-1">
      <span className="flex h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${formatQuantity(String(still))} ${m.unit} still needed: ${formatQuantity(String(hand))} on hand, ${formatQuantity(String(order))} on order, ${formatQuantity(String(short))} short`}>
        {hand > 0 && <span className="bg-success" style={{ width: w(hand) }} />}
        {order > 0 && <span className="bg-info" style={{ width: w(order) }} />}
        {short > 0 && <span className="bg-destructive" style={{ width: w(short) }} />}
      </span>
      <span className="text-[11px] text-muted-foreground tabular-nums">
        <span className="font-semibold text-foreground">{formatQuantity(m.still_needed)}</span> {m.unit} to go
      </span>
    </span>
  )
}

function ShortPill({ m }: { m: M }) {
  if (m.short_by === null) return <span className="text-muted-foreground">—</span>
  const short = n(m.short_by) > 0
  return (
    <Pill tone={short ? 'bad' : 'good'} icon={short ? PackageX : PackageCheck} size="xs">
      {short ? `${formatQuantity(m.short_by)} ${m.unit} short` : 'Enough'}
    </Pill>
  )
}

function Reason({ m, projectId }: { m: M; projectId: string }) {
  const fix =
    m.reason === 'no_usage_recorded' ? { to: `/materials?view=movements&dir=out&material=${m.material_id}&project=${projectId}`, label: 'Record use' }
    : m.reason === 'unit_differs' || m.reason === 'used_no_work' ? { to: `/projects/${projectId}/boq`, label: m.reason === 'unit_differs' ? 'Fix the unit' : 'Check the BOQ' }
    : null
  return <ReasonChip tone={COLOUR_TONE[m.colour]} icon={LOOK[m.colour].icon} label={REASON[m.reason]} title={why(m)} fix={fix} />
}

/** UX-43/44: the Numbers view's columns: every figure the API gives, in its own column. */
const qty = (v: string | null) => (v === null ? null : n(v) === 0 ? <span className="text-muted-foreground">0</span> : formatQuantity(v))
const NAME: NumberColumn<M> = {
  key: 'material',
  label: 'Material',
  sortValue: (m) => m.material.toLowerCase(),
  cell: (m) => (
    <span className="flex items-center gap-1.5 whitespace-nowrap" title={why(m)}>
      {React.createElement(LOOK[m.colour].icon, { className: cn('size-3.5 shrink-0', COLOUR_TEXT[m.colour]), 'aria-hidden': true })}
      <span className="font-medium">{m.material}</span>
      <span className="text-[11px] text-muted-foreground">{m.unit}</span>
    </span>
  ),
}
const COLUMNS: NumberColumn<M>[] = [
  { key: 'required', label: 'BOQ needs', title: 'For the whole BOQ', sortValue: (m) => n(m.required_total), cell: (m) => qty(m.required_total) },
  { key: 'should', label: 'Work needed', title: 'What the work done so far needed', sortValue: (m) => n(m.should_have_used), cell: (m) => qty(m.should_have_used) },
  { key: 'used', label: 'Used', title: 'Used on site', sortValue: (m) => n(m.used), cell: (m) => qty(m.used), tone: (m) => (n(m.used) ? COLOUR_TEXT[m.colour] : undefined) },
  {
    key: 'over', label: 'Over the work', title: 'Used − what the work needed', sortValue: (m) => (m.used_over_work === null ? null : n(m.used_over_work)),
    cell: (m) => (m.used_over_work === null ? null : n(m.used_over_work) === 0 ? qty('0') : `${n(m.used_over_work) > 0 ? '+' : ''}${formatQuantity(m.used_over_work)}`),
    tone: (m) => (n(m.used_over_work) > 0 ? 'font-semibold text-destructive' : n(m.used_over_work) < 0 ? 'font-semibold text-success' : undefined),
  },
  { key: 'received', label: 'Received', title: 'Delivered to site', sortValue: (m) => n(m.received), cell: (m) => qty(m.received) },
  { key: 'hand', label: 'On hand', title: 'In stock now', sortValue: (m) => n(m.on_hand), cell: (m) => qty(m.on_hand), tone: (m) => (n(m.on_hand) ? 'text-success' : undefined) },
  { key: 'order', label: 'On order', title: 'Ordered, not yet in', sortValue: (m) => n(m.on_order), cell: (m) => qty(m.on_order), tone: (m) => (n(m.on_order) ? 'text-info' : undefined) },
  { key: 'still', label: 'Still needed', title: 'To finish the BOQ', sortValue: (m) => n(m.still_needed), cell: (m) => qty(m.still_needed) },
  {
    key: 'short', label: 'Short', title: 'Still needed beyond stock and orders', sortValue: (m) => (m.short_by === null ? null : n(m.short_by)), cell: (m) => qty(m.short_by),
    tone: (m) => (n(m.short_by) > 0 ? 'font-semibold text-destructive' : undefined),
  },
]

const SORTS: { value: string; label: string; key?: (m: M) => number | string }[] = [
  { value: '', label: 'Worst first' },
  { value: 'short', label: 'Most short to finish', key: (m) => -n(m.short_by) },
  { value: 'over', label: 'Most used over the work', key: (m) => -n(m.used_over_work) },
  { value: 'still', label: 'Most still needed', key: (m) => -n(m.still_needed) },
  { value: 'name', label: 'Name', key: (m) => m.material.toLowerCase() },
]

export default function CostMaterialsPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const navigate = useNavigate()
  usePageTitle('Materials vs BOQ')
  const allowed = maySeeBoq(me?.role)
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : null
  const q = useQuery({
    queryKey: ['cost', 'materials', projectId],
    queryFn: () => fetchProjectMaterials(projectId!),
    enabled: allowed && !!projectId,
  })
  const [search, setSearch] = useUrlState<string>('q', '')
  const [colour, setColour] = useUrlState<string>('colour', '')
  const [shortOnly, setShortOnly] = useUrlState<string>('short', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  // UX-43/44: Bars (a glance) or Numbers (every figure in its own column, any column sorts).
  const [show, setShow] = useShowMode('costmat')
  const { col, dir, onSort: sortCol, clear: clearCol } = useColumnSort()
  const needle = search.trim().toLowerCase()
  const listed = React.useMemo(() => {
    const out = (q.data?.materials ?? []).filter(
      (m) => (!colour || m.colour === colour) && (!shortOnly || n(m.short_by) > 0) && (!needle || m.material.toLowerCase().includes(needle)),
    )
    const byColumn = show === 'numbers' ? sortByColumn(out, [NAME, ...COLUMNS], col, dir) : null
    if (byColumn) return byColumn
    const key = SORTS.find((x) => x.value === sort)?.key
    if (!key) return out
    return [...out].sort((a, b) => {
      const ka = key(a)
      const kb = key(b)
      return typeof ka === 'string' ? ka.localeCompare(String(kb)) : ka - Number(kb)
    })
  }, [q.data, colour, shortOnly, needle, sort, show, col, dir])
  // UX-37: numbered pages, kept in the address.
  const paged = usePagedUrl(listed)

  if (!allowed) return <NoAccess roles={MONEY_PEOPLE} />
  const header = <DprHeader back={{ to: '/cost', label: 'Overview' }} crumb="Cost control" title="Materials vs BOQ" date={projectId ? undefined : 'Pick a project'} />
  if (!projectId) {
    return (
      <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
        {header}
        {/* UX-35: the one project picker (cards, one project opens by itself). */}
        <ProjectPickList to={(id) => `/cost/materials?project=${id}`} empty="No projects yet." />
      </div>
    )
  }
  if (q.isError) return <PageError message="Materials vs BOQ could not be loaded." onRetry={() => q.refetch()} back={{ to: '/cost', label: 'Overview' }} />
  const d = q.data
  const all = d?.materials ?? []
  const count = (c: VarianceColour) => d?.summary[c] ?? 0
  const judged = ORDER.reduce((t, c) => t + count(c), 0)
  const shortCount = all.filter((m) => n(m.short_by) > 0).length
  const lines = (d?.lines_with_norms ?? 0) + (d?.lines_without_norms ?? 0)
  const any = !!(search || colour || shortOnly)
  const clear = () => {
    setSearch('')
    setColour('')
    setShortOnly('')
  }
  const exportShown = () =>
    exportCsv(
      `materials-vs-boq-${d?.date ?? ''}.csv`,
      ['Material', 'Unit', 'Colour', 'Why', 'BOQ needs', 'Work done needed', 'Used', 'Used over the work', 'Received', 'On hand', 'On order', 'Still needed', 'Short to finish'],
      listed.map((m) => [
        m.material, m.unit, COLOUR_WORD[m.colour], REASON[m.reason], m.required_total, m.should_have_used, m.used, m.used_over_work ?? '', m.received, m.on_hand,
        m.on_order, m.still_needed, m.short_by ?? '',
      ]),
    )

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      {header}
      {q.isLoading || !d ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : all.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-4 py-10 text-center" data-guide="costmat.empty">
          <span className="flex size-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" aria-hidden>
            <PackageSearch className="size-5" />
          </span>
          <p className="font-medium">No BOQ line has its materials per unit yet</p>
          <Button asChild size="sm">
            <Link to={`/projects/${projectId}/boq`}>Add them on the BOQ</Link>
          </Button>
        </div>
      ) : (
        <>
          <KpiStrip
            guide="costmat.stats"
            stats={[
              { label: 'Used over the work', icon: TriangleAlert, tone: count('red') > 0 ? 'bad' : count('amber') > 0 ? 'attention' : 'good', value: count('red') + count('amber'), of: judged || undefined, hint: `${count('red')} red · ${count('amber')} amber` },
              { label: 'Within the BOQ', icon: CircleCheck, tone: 'good', value: count('green'), of: judged || undefined },
              { label: 'Short to finish', icon: PackageX, tone: d.short_at_completion > 0 ? 'bad' : 'good', value: d.short_at_completion, hint: 'beyond stock and orders' },
              { label: 'Not judged', icon: CircleDashed, value: count('grey') },
              { label: 'Lines with materials', icon: ClipboardList, tone: d.lines_without_norms > 0 ? 'attention' : 'good', value: d.lines_with_norms, of: lines || undefined },
            ]}
          />

          {d.lines_without_norms > 0 && (
            <ActionChip icon={PackageSearch} to={`/projects/${projectId}/boq`} action="Set them">
              <span className="font-semibold tabular-nums">{d.lines_without_norms}</span> BOQ {d.lines_without_norms === 1 ? 'line has' : 'lines have'} no materials set
              <span className="text-muted-foreground"> · not counted here</span>
            </ActionChip>
          )}

          <DprSection icon={Package} title="Materials" meta={any ? `${listed.length} of ${all.length}` : all.length}>
            {/* The materials by colour: one bar, each colour a filter; "short to finish" another (UX-45 list kit). */}
            <div className="mb-2">
              <StateBar
                items={ORDER.map((c) => ({ value: c, label: COLOUR_WORD[c], count: count(c), icon: LOOK[c].icon, tone: COLOUR_TONE[c] }))}
                value={colour}
                onChange={setColour}
                extra={<ToggleChip on={!!shortOnly} onClick={() => setShortOnly(shortOnly ? '' : '1')} icon={PackageX} count={shortCount} label="short to finish" tone="bad" />}
                right={
                  <>
                    <SearchBox value={search} onChange={setSearch} placeholder="Search materials" size="sm" />
                    <SortSelect value={col ? '' : sort} options={SORTS} onChange={(v) => { setSort(v); clearCol() }} label="Sort the materials" size="sm" />
                    <ClearButton show={any} onClick={clear} size="sm" />
                    <ShowSwitch show={show} onShow={setShow} label="How to show the materials" />
                    <ActionButton kind="export-excel" size="sm" className="h-8" disabled={listed.length === 0} onClick={exportShown} title="The materials shown, as a CSV file (opens in Excel)">
                      <span className="hidden sm:inline">{any ? 'Export shown' : 'Export'}</span>
                    </ActionButton>
                  </>
                }
              />
            </div>

            {listed.length === 0 ? (
              <NoMatch noun="material" onClear={clear} />
            ) : show === 'numbers' ? (
              <NumbersTable
                rows={paged.shown}
                rowKey={(m) => m.material_id}
                first={NAME}
                columns={COLUMNS}
                edge={(m) => COLOUR_DOT[m.colour]}
                col={col}
                dir={dir}
                onSort={sortCol}
                onOpen={(m) => navigate(`/materials?view=movements&material=${m.material_id}&project=${projectId}`)}
                openTitle="Open its stock book"
                guide="costmat.list"
                minWidth={980}
                footer="Each in its own unit · the colour edge and icon: used against what the work needed · hover a name for why"
              />
            ) : (
              <div className="overflow-hidden rounded-xl border bg-card" data-guide="costmat.list">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Material</th>
                      <th className="hidden w-56 px-3 py-2 text-left font-medium md:table-cell">Used vs work needed</th>
                      <th className="hidden w-52 px-3 py-2 text-left font-medium lg:table-cell">To finish</th>
                      <th className="px-3 py-2 text-right font-medium">Stock</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {paged.shown.map((m) => (
                      <tr
                        key={m.material_id}
                        className="cursor-pointer align-top hover:bg-muted/30"
                        onClick={() => navigate(`/materials?view=movements&material=${m.material_id}&project=${projectId}`)}
                        title="Open its stock book"
                      >
                        <td className="relative px-3 py-2.5 pl-4">
                          <span className={cn('absolute top-2 bottom-2 left-1.5 w-1 rounded-full', COLOUR_DOT[m.colour])} aria-hidden />
                          <span className="flex flex-col gap-1">
                            <span className="flex items-baseline gap-2">
                              <span className="font-medium">{m.material}</span>
                              <span className="text-[11px] text-muted-foreground">
                                {m.unit} · {m.lines} {m.lines === 1 ? 'line' : 'lines'}
                              </span>
                            </span>
                            <Reason m={m} projectId={projectId} />
                            {/* Below a laptop the bars fold under the name (docs/DESIGN.md section 8). */}
                            <span className="flex max-w-72 flex-col gap-2 pt-1 md:hidden">
                              <UsedBar m={m} />
                              <FinishBar m={m} />
                              <span className="text-[11px] text-muted-foreground tabular-nums sm:hidden">
                                {formatQuantity(m.on_hand)} on hand{n(m.on_order) > 0 ? ` · ${formatQuantity(m.on_order)} ordered` : ''}
                              </span>
                            </span>
                            <span className="hidden max-w-60 pt-1 md:block lg:hidden">
                              <FinishBar m={m} />
                            </span>
                          </span>
                        </td>
                        <td className="hidden px-3 py-2.5 md:table-cell">
                          <UsedBar m={m} />
                        </td>
                        <td className="hidden px-3 py-2.5 lg:table-cell">
                          <FinishBar m={m} />
                        </td>
                        <td className="w-px px-3 py-2.5 text-right">
                          <span className="flex flex-col items-end gap-1">
                            <ShortPill m={m} />
                            <span className="hidden text-[11px] whitespace-nowrap text-muted-foreground tabular-nums sm:block">
                              {formatQuantity(m.on_hand)} on hand{n(m.on_order) > 0 ? ` · ${formatQuantity(m.on_order)} ordered` : ''}
                            </span>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pager {...paged.pager} noun="materials" className="mt-2" />
            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
              <Legend
                items={[
                  { tone: 'good', label: 'Within what the work needed' },
                  { tone: 'attention', label: 'Up to 10% more' },
                  { tone: 'bad', label: 'More than 10% over' },
                ]}
              />
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                To finish:
                <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-success" aria-hidden /> on hand</span>
                <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-info" aria-hidden /> on order</span>
                <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-destructive" aria-hidden /> short</span>
              </span>
            </div>
          </DprSection>
        </>
      )}
    </div>
  )
}
