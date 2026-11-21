import * as React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { LucideIcon } from 'lucide-react'
import {
  Ban, Check, CircleCheck, CircleDashed, CircleX, Clock, FilePlus2, Hourglass, Layers, ListPlus, Pencil, Plus, Send, Trash2, TrendingUp, X,
} from 'lucide-react'
import { DprHeader, PageError } from '@/components/dpr-page'
import {
  ActionButton, ActionChip, ClearButton, KpiStrip, Legend, NoAccess, NoMatch, Pager, Pill, SearchBox, SortSelect, StateBar,
} from '@/components/page/page-kit'
import { ByLine, Fact, Facts, SheetHero, SheetSection } from '@/components/detail-sheet'
import { Button } from '@/components/ui/button'
import { DatePicker } from '@/components/ui/date-picker'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetFooter, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ui/toast-notification'
import { useAuth } from '@/lib/AuthContext'
import { fetchBoq, formatRupees, formatRupeesShort } from '@/lib/boq'
import { appNow } from '@/lib/clock'
import { localIsoDate } from '@/lib/site-day'
import { mayManageMoney } from '@/lib/cost'
import { exportCsv } from '@/lib/export'
import { TONE, type Tone } from '@/lib/list-kit'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { usePagedUrl } from '@/lib/paging'
import { BOOKS_PEOPLE } from '@/lib/permissions'
import { fetchProjects } from '@/lib/projects'
import { useScope } from '@/lib/ScopeContext'
import { updateParams, useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'
import {
  actOnVariation, createVariation, deleteVariation, fetchVariations, updateVariation,
  type Variation, type VariationAct, type VariationInput, type VariationKind, type VariationStatus,
} from '@/lib/variations'

// NXT-04 / CC-24: extra or changed work the client asked for, priced, sent, approved, then billed. On the list kit
// (docs/design/LIST_PAGE_KIT.md): the money in figures, the one thing to chase, the states as a bar, rows with the
// amount, the margin and (once approved) how much of it is billed; a panel with its story and its actions. Approving
// puts it on the BOQ (a VO line, or more of a line), so the site's work on it is measured and billed on RA bills.

const STATES: { value: VariationStatus; label: string; icon: LucideIcon; tone: Tone }[] = [
  { value: 'draft', label: 'Draft', icon: CircleDashed, tone: 'muted' },
  { value: 'sent', label: 'With the client', icon: Hourglass, tone: 'attention' },
  { value: 'approved', label: 'Approved', icon: CircleCheck, tone: 'good' },
  { value: 'rejected', label: 'Rejected', icon: CircleX, tone: 'bad' },
  { value: 'cancelled', label: 'Cancelled', icon: Ban, tone: 'muted' },
]
const STATE = Object.fromEntries(STATES.map((s) => [s.value, s])) as Record<VariationStatus, (typeof STATES)[number]>

const SORTS = [
  { value: '', label: 'Needs you first' },
  { value: 'newest', label: 'Newest' },
  { value: 'amount', label: 'Biggest' },
  { value: 'waiting', label: 'Waiting longest' },
]
/** A client who has had it two weeks is chased. */
const CHASE_DAYS = 14
const UNITS = ['sqm', 'sqft', 'cum', 'rmt', 'rft', 'nos', 'kg', 'ton', 'ls', 'month', 'job']

const money = (v: string | number | null | undefined) => formatRupeesShort(v === null || v === undefined ? null : String(v))
const full = (v: string | number | null | undefined) => formatRupees(v === null || v === undefined ? null : String(v))
const day = (iso: string | null) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
const qty = (v: string | null) => (v === null ? '—' : String(Number(v)))

/** Green 15% and up, amber below, red at a loss, grey when our cost was not priced. */
function marginTone(v: Variation): Tone {
  if (v.margin_pct === null) return 'muted'
  const p = Number(v.margin_pct)
  return p < 0 ? 'bad' : p < 15 ? 'attention' : 'good'
}

export default function VariationsPage() {
  const { me } = useAuth()
  const { scope } = useScope()
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  usePageTitle('Variations')
  const allowed = mayManageMoney(me?.role)
  const projectId = scope.mode !== 'portfolio' ? scope.projectId : undefined

  const q = useQuery({ queryKey: ['variations', projectId ?? null], queryFn: () => fetchVariations(projectId), enabled: allowed })
  const items = React.useMemo(() => q.data?.items ?? [], [q.data])

  const [search, setSearch] = useUrlState<string>('q', '')
  const [state, setState] = useUrlState<string>('state', '')
  const [chase, setChase] = useUrlState<string>('chase', '')
  const [sort, setSort] = useUrlState<string>('sort', '')
  const [openId, setOpenId] = useUrlState<string>('id', '')
  const openPanel = (id: string) => updateParams(setParams, (p) => p.set('id', id), !!openId)

  const listed = React.useMemo(() => {
    const s = search.trim().toLowerCase()
    const out = items.filter((v) =>
      (!state || v.status === state) &&
      (!chase || (v.status === 'sent' && (v.waiting_days ?? 0) >= CHASE_DAYS)) &&
      (!s || [v.ref, v.title, v.description, v.project, v.asked_by, v.line?.work].some((x) => (x || '').toLowerCase().includes(s))))
    const rank: Record<VariationStatus, number> = { sent: 0, draft: 1, approved: 2, rejected: 3, cancelled: 4 }
    return [...out].sort((a, b) => {
      if (sort === 'newest') return b.asked_on.localeCompare(a.asked_on) || b.number - a.number
      if (sort === 'amount') return Number(b.amount) - Number(a.amount)
      if (sort === 'waiting') return (b.waiting_days ?? -1) - (a.waiting_days ?? -1)
      return rank[a.status] - rank[b.status] || (b.waiting_days ?? 0) - (a.waiting_days ?? 0) || b.asked_on.localeCompare(a.asked_on)
    })
  }, [items, search, state, chase, sort])
  const paged = usePagedUrl(listed)
  const any = !!(search || state || chase)
  const clear = () => { setSearch(''); setState(''); setChase('') }

  const act = useMutation({
    mutationFn: ({ id, how, body }: { id: string; how: VariationAct; body?: { decided_by?: string | null; decided_on?: string | null; note?: string | null } }) => actOnVariation(id, how, body),
    onSuccess: (v, { how }) => {
      const words: Record<VariationAct, string> = { send: 'Marked as sent to the client', approve: 'Approved: it is on the BOQ', reject: 'Marked rejected', cancel: 'Cancelled' }
      toast.success(`${v.ref}: ${words[how]}`, how === 'approve' ? (v.kind === 'new' ? `A line ${v.ref} in the "Variations" section; site work on it is billed on the next RA bill.` : `${v.line?.work ?? 'Its line'} grows by ${qty(v.quantity)} ${v.unit}.`) : undefined)
      qc.invalidateQueries({ queryKey: ['variations'] })
      qc.invalidateQueries({ queryKey: ['boq'] })
    },
    onError: (err: unknown) => toast.error('Could not change it', apiErrorMessage(err)),
  })
  const remove = useMutation({
    mutationFn: deleteVariation,
    onSuccess: () => { toast.success('Draft removed'); setOpenId(''); qc.invalidateQueries({ queryKey: ['variations'] }) },
    onError: (err: unknown) => toast.error('Could not remove it', apiErrorMessage(err)),
  })

  const [editing, setEditing] = React.useState<{ open: boolean; v: Variation | null }>({ open: false, v: null })
  // The saved one's panel opens once the form has closed: opened while the form is still closing, the panel reads it
  // as a click outside and closes again.
  const openAfterClose = React.useRef<string | null>(null)
  const [deciding, setDeciding] = React.useState<{ v: Variation; how: 'approve' | 'reject' } | null>(null)

  if (!allowed) return <NoAccess roles={BOOKS_PEOPLE} />
  if (q.isError) return <PageError message="Variations could not be loaded." onRetry={() => q.refetch()} back={{ to: '/billing/ra-bills', label: 'RA bills' }} />

  const s = q.data?.summary
  const openV = items.find((v) => v.id === openId) ?? null
  const at = listed.findIndex((v) => v.id === openId)
  const toChase = items.filter((v) => v.status === 'sent' && (v.waiting_days ?? 0) >= CHASE_DAYS)
  const approvedNotBilled = s ? Number(s.approved) - Number(s.billed) : 0
  const link = (set: Record<string, string>) => {
    const next = new URLSearchParams()
    for (const k of ['project', 'site']) if (params.get(k)) next.set(k, params.get(k)!)
    for (const [k, v] of Object.entries(set)) next.set(k, v)
    return `/billing/variations?${next}`
  }

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <DprHeader
        back={{ to: '/billing/ra-bills', label: 'RA bills' }}
        crumb="Client billing"
        title="Variations"
        action={
          <Button size="sm" className="gap-1.5 font-semibold" onClick={() => setEditing({ open: true, v: null })} data-guide="variations.add">
            <Plus className="size-4" /> New variation
          </Button>
        }
      />

      {q.isLoading || !s ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-20 rounded-xl" />
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-lg" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-4 py-12 text-center">
          <span className="flex size-10 items-center justify-center rounded-xl bg-info-soft text-info" aria-hidden><FilePlus2 className="size-5" /></span>
          <p className="font-medium">No variation yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">Price extra work here before it is built.</p>
          <Button size="sm" onClick={() => setEditing({ open: true, v: null })}><Plus className="size-4" /> New variation</Button>
        </div>
      ) : (
        <>
          <KpiStrip
            guide="variations.stats"
            stats={[
              { label: 'With the client', icon: Hourglass, value: money(s.waiting), tone: Number(s.waiting) > 0 ? 'attention' : 'default', hint: `${s.counts.sent} not answered`, onClick: () => setState(state === 'sent' ? '' : 'sent'), pressed: state === 'sent' },
              { label: 'Approved', icon: CircleCheck, value: money(s.approved), tone: 'good', hint: s.days_added ? `${s.days_added} days added` : `${s.counts.approved} ${s.counts.approved === 1 ? 'variation' : 'variations'}`, onClick: () => setState(state === 'approved' ? '' : 'approved'), pressed: state === 'approved' },
              { label: 'Billed of approved', icon: TrendingUp, value: money(s.billed), tone: 'info', share: Number(s.approved) ? Number(s.billed) / Number(s.approved) : undefined, hint: approvedNotBilled > 0 ? `${money(approvedNotBilled)} still to bill` : undefined },
              { label: 'Rejected', icon: CircleX, value: Number(s.rejected) ? money(s.rejected) : '—', tone: Number(s.rejected) ? 'bad' : 'default', hint: `${s.counts.rejected} ${s.counts.rejected === 1 ? 'variation' : 'variations'}` },
            ]}
          />

          {toChase.length > 0 ? (
            <ActionChip icon={Clock} to={link({ chase: '1' })} action="Show them">
              <span className="font-semibold tabular-nums">{toChase.length}</span> with the client {CHASE_DAYS}+ days: <span className="font-semibold tabular-nums">{money(toChase.reduce((t, v) => t + Number(v.amount), 0))}</span> not answered
            </ActionChip>
          ) : s.counts.draft > 0 ? (
            <ActionChip icon={Send} to={link({ state: 'draft' })} action="Send them">
              <span className="font-semibold tabular-nums">{s.counts.draft}</span> {s.counts.draft === 1 ? 'draft is' : 'drafts are'} not sent to the client yet
            </ActionChip>
          ) : null}

          <StateBar
            guide="variations.states"
            items={STATES.map((st) => ({ ...st, count: s.counts[st.value] }))}
            value={state}
            onChange={setState}
            extra={chase ? <button type="button" onClick={() => setChase('')} className="inline-flex items-center gap-1 rounded-full bg-foreground px-2.5 py-1 text-xs font-semibold text-background"><Clock className="size-3.5" /> {CHASE_DAYS}+ days <X className="size-3" /></button> : null}
          >
            <div className="flex flex-wrap items-center gap-2" data-guide="variations.search">
              <SearchBox value={search} onChange={setSearch} placeholder="Search VO, work, client" label="Search variations" size="sm" />
              <ClearButton show={any} onClick={clear} size="sm" />
              <span className="ml-auto flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground tabular-nums">{listed.length === items.length ? listed.length : `${listed.length} of ${items.length}`}</span>
                <SortSelect value={sort} options={SORTS} onChange={setSort} label="Sort the variations" size="sm" />
                <ActionButton kind="export-excel" size="sm" className="h-8" disabled={listed.length === 0} onClick={() => exportShown(listed)} title="The variations shown, as a CSV file (opens in Excel)">
                  <span className="hidden sm:inline">{any ? 'Export shown' : 'Export'}</span>
                </ActionButton>
              </span>
            </div>
          </StateBar>

          {listed.length === 0 ? (
            <NoMatch noun="variation" onClear={clear} />
          ) : (
            <div className="overflow-hidden rounded-xl border bg-card" data-guide="variations.list">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Variation</th>
                    <th className="hidden w-44 px-3 py-2 text-right font-medium md:table-cell">Quantity × rate</th>
                    <th className="w-28 px-3 py-2 text-right font-medium">Amount</th>
                    <th className="hidden w-44 px-3 py-2 text-left font-medium lg:table-cell">Billed</th>
                    <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {paged.shown.map((v) => (
                    <Row key={v.id} v={v} showProject={!projectId} onOpen={() => openPanel(v.id)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager {...paged.pager} noun="variations" />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            <Legend items={[{ tone: 'good', label: 'Margin 15%+' }, { tone: 'attention', label: 'Under 15%' }, { tone: 'bad', label: 'At a loss' }, { tone: 'default', label: 'Our cost not priced' }]} />
          </div>
        </>
      )}

      <Sheet open={!!openId} onOpenChange={(o) => { if (!o) setOpenId('') }}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-md">
          {openV ? (
            <Panel
              v={openV}
              position={at >= 0 ? { at, of: listed.length } : null}
              onStep={(d) => { const n = listed[at + d]; if (n) setOpenId(n.id) }}
              busy={act.isPending || remove.isPending}
              onAct={(how) => act.mutate({ id: openV.id, how })}
              onDecide={(how) => setDeciding({ v: openV, how })}
              onEdit={() => setEditing({ open: true, v: openV })}
              onDelete={() => remove.mutate(openV.id)}
            />
          ) : (
            <div className="flex flex-col gap-3 p-5">
              <SheetTitle className="sr-only">Variation</SheetTitle>
              {q.isLoading ? <Skeleton className="h-40 rounded-xl" /> : <p className="text-sm text-muted-foreground">This variation is not in your list.</p>}
            </div>
          )}
        </SheetContent>
      </Sheet>

      <VariationDialog
        open={editing.open}
        v={editing.v}
        projectId={projectId}
        onClose={() => setEditing({ open: false, v: null })}
        onSaved={(v) => { qc.invalidateQueries({ queryKey: ['variations'] }); openAfterClose.current = v.id; setEditing({ open: false, v: null }) }}
        onClosed={() => { const id = openAfterClose.current; openAfterClose.current = null; if (id && id !== openId) openPanel(id) }}
      />
      <DecideDialog
        target={deciding}
        busy={act.isPending}
        onClose={() => setDeciding(null)}
        onDecide={(body) => {
          if (!deciding) return
          act.mutate({ id: deciding.v.id, how: deciding.how, body }, { onSuccess: () => setDeciding(null) })
        }}
      />
    </div>
  )
}

function exportShown(rows: Variation[]) {
  exportCsv(
    'variations.csv',
    ['VO', 'Project', 'Work', 'Kind', 'Quantity', 'Unit', 'Client rate', 'Amount', 'Our cost', 'Margin', 'Days added', 'Asked by', 'Asked on', 'State', 'Decided on', 'Decided by', 'Billed'],
    rows.map((v) => [v.ref, v.project, v.title, v.kind === 'new' ? 'New item' : `More of ${v.line?.work ?? ''}`, v.quantity, v.unit, v.client_rate, v.amount, v.cost_estimate ?? '', v.margin ?? '', v.days_added ?? '', v.asked_by ?? '', v.asked_on, STATE[v.status].label, v.decided_on ?? '', v.decided_by ?? '', v.billed_amount ?? '']),
  )
}

function StatePill({ v }: { v: Variation }) {
  const st = STATE[v.status]
  return <Pill tone={st.tone} icon={st.icon}>{st.label}</Pill>
}

function KindTag({ v }: { v: Variation }) {
  return v.kind === 'new'
    ? <span className="inline-flex items-center gap-1 rounded-md bg-info-soft px-1.5 py-px text-[11px] font-medium text-info"><ListPlus className="size-3" aria-hidden />New item</span>
    : <span className="inline-flex max-w-56 items-center gap-1 rounded-md bg-muted px-1.5 py-px text-[11px] font-medium text-muted-foreground" title={v.line?.work ?? undefined}><Layers className="size-3 shrink-0" aria-hidden /><span className="truncate">More of {v.line?.code ? `${v.line.code} ` : ''}{v.line?.work}</span></span>
}

/** For an approved new item: how much of it the site has done and the client has been billed for. */
function BilledBar({ v }: { v: Variation }) {
  if (v.status !== 'approved') return null
  if (v.kind === 'more') return <span className="text-[11px] text-muted-foreground">Billed with its line</span>
  const q = Number(v.quantity)
  const done = Math.min(Number(v.done ?? 0), q)
  const billed = Math.min(Number(v.billed ?? 0), q)
  return (
    <span className="flex w-full max-w-40 flex-col gap-1" title={`${qty(v.done)} of ${qty(v.quantity)} ${v.unit} done, ${qty(v.billed)} billed`}>
      <span className="relative h-1.5 overflow-hidden rounded-full bg-muted">
        <span className="absolute inset-y-0 left-0 rounded-full bg-info/40" style={{ width: `${(done / q) * 100}%` }} />
        <span className="absolute inset-y-0 left-0 rounded-full bg-success" style={{ width: `${(billed / q) * 100}%` }} />
      </span>
      <span className="text-[11px] text-muted-foreground tabular-nums">{money(v.billed_amount)} billed · {Math.round((done / q) * 100)}% done</span>
    </span>
  )
}

function Row({ v, showProject, onOpen }: { v: Variation; showProject: boolean; onOpen: () => void }) {
  const st = STATE[v.status]
  const late = v.status === 'sent' && (v.waiting_days ?? 0) >= CHASE_DAYS
  return (
    <tr className={cn('cursor-pointer align-top hover:bg-muted/30', (v.status === 'cancelled' || v.status === 'rejected') && 'text-muted-foreground')} onClick={onOpen} title="Open the variation" data-record-id={v.id}>
      <td className="relative px-3 py-2.5 pl-4">
        <span className={cn('absolute top-2 bottom-2 left-1.5 w-1 rounded-full', TONE[st.tone].dot)} aria-hidden />
        <span className="flex flex-col gap-0.5">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-xs font-semibold text-muted-foreground tabular-nums">{v.ref}</span>
            <span className="font-medium text-foreground">{v.title}</span>
          </span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <KindTag v={v} />
            {showProject && <span>{v.project}</span>}
            {v.asked_by && <span>asked by {v.asked_by}</span>}
            <span>{day(v.asked_on)}</span>
            {v.days_added ? <span>+{v.days_added} days</span> : null}
          </span>
          <span className="pt-1 text-[11px] text-muted-foreground tabular-nums md:hidden">{qty(v.quantity)} {v.unit} × {full(v.client_rate)}</span>
          {/* Phones: the state under the name (its column is for wider screens). */}
          <span className="flex items-center gap-1.5 pt-1 sm:hidden">
            <StatePill v={v} />
            {v.status === 'sent' && <span className={cn('text-[11px] tabular-nums', late ? 'font-semibold text-destructive' : 'text-muted-foreground')}>{v.waiting_days} days</span>}
          </span>
          <span className="pt-1 lg:hidden"><BilledBar v={v} /></span>
        </span>
      </td>
      <td className="hidden px-3 py-2.5 text-right text-xs text-muted-foreground tabular-nums md:table-cell">{qty(v.quantity)} {v.unit} × {full(v.client_rate)}</td>
      <td className="px-3 py-2.5 text-right">
        <span className="flex flex-col items-end gap-1">
          <span className="font-semibold tabular-nums" title={full(v.amount)}>{money(v.amount)}</span>
          <Pill tone={marginTone(v)} size="xs" title={v.margin === null ? 'Our cost was not priced' : `Margin ${full(v.margin)}`}>
            {v.margin_pct === null ? 'cost?' : `${Number(v.margin_pct)}%`}
          </Pill>
        </span>
      </td>
      <td className="hidden px-3 py-2.5 lg:table-cell"><BilledBar v={v} /></td>
      <td className="hidden w-px px-3 py-2.5 text-right sm:table-cell">
        <span className="flex flex-col items-end gap-1">
          <StatePill v={v} />
          {v.status === 'sent' && <span className={cn('text-[11px] tabular-nums whitespace-nowrap', late ? 'font-semibold text-destructive' : 'text-muted-foreground')}>{v.waiting_days} days</span>}
          {v.status === 'approved' && v.decided_on && <span className="text-[11px] whitespace-nowrap text-muted-foreground">{day(v.decided_on)}</span>}
        </span>
      </td>
    </tr>
  )
}

function Panel({ v, position, onStep, busy, onAct, onDecide, onEdit, onDelete }: {
  v: Variation
  position: { at: number; of: number } | null
  onStep: (d: -1 | 1) => void
  busy: boolean
  onAct: (how: VariationAct) => void
  onDecide: (how: 'approve' | 'reject') => void
  onEdit: () => void
  onDelete: () => void
}) {
  const open = v.status === 'draft' || v.status === 'sent'
  const tone = v.status === 'approved' ? 'in' : v.status === 'rejected' ? 'out' : v.status === 'sent' ? 'warn' : 'neutral'
  const steps: { label: string; when: string | null; tone: Tone; done: boolean }[] = [
    { label: v.asked_by ? `Asked by ${v.asked_by}` : 'Asked for', when: v.asked_on, tone: 'muted', done: true },
    { label: 'Sent to the client', when: v.sent_on, tone: 'attention', done: !!v.sent_on },
    v.status === 'rejected'
      ? { label: `Rejected${v.decided_by ? ` by ${v.decided_by}` : ''}`, when: v.decided_on, tone: 'bad', done: true }
      : v.status === 'cancelled'
        ? { label: 'Cancelled', when: null, tone: 'muted', done: true }
        : { label: `Approved${v.decided_by ? ` by ${v.decided_by}` : ''}`, when: v.decided_on, tone: 'good', done: v.status === 'approved' },
    ...(v.status === 'approved' || open
      ? [{ label: v.kind === 'new' ? `On the BOQ as ${v.ref}` : `Its BOQ line grows by ${qty(v.quantity)} ${v.unit}`, when: null, tone: 'info' as Tone, done: v.status === 'approved' }]
      : []),
    ...(v.status === 'approved' && v.kind === 'new'
      ? [{ label: Number(v.billed ?? 0) > 0 ? `${money(v.billed_amount)} billed (${qty(v.billed)} ${v.unit})` : 'Not billed yet', when: null, tone: 'good' as Tone, done: Number(v.billed ?? 0) > 0 }]
      : []),
  ]
  return (
    <>
      <div className="flex items-center gap-1 border-b px-3 py-1.5 text-xs text-muted-foreground">
        {position && (
          <>
            <Button variant="ghost" size="icon" className="size-7" disabled={position.at <= 0} onClick={() => onStep(-1)} aria-label="Previous variation">‹</Button>
            <span className="tabular-nums">{position.at + 1} of {position.of}</span>
            <Button variant="ghost" size="icon" className="mr-8 size-7" disabled={position.at >= position.of - 1} onClick={() => onStep(1)} aria-label="Next variation">›</Button>
          </>
        )}
      </div>
      <SheetHero tone={tone} kicker={`${v.ref} · ${STATE[v.status].label}`} title={v.title}>
        <span>{v.project}</span>
        <span className="font-semibold text-foreground">{full(v.amount)}</span>
      </SheetHero>

      {v.description && (
        <SheetSection title="What the client asked">
          <p className="text-sm leading-relaxed">{v.description}</p>
        </SheetSection>
      )}

      <SheetSection title="The price" className="border-t">
        <Facts>
          <Fact label="Kind"><KindTag v={v} /></Fact>
          <Fact label="Quantity">{qty(v.quantity)} {v.unit}</Fact>
          <Fact label="Client rate">{full(v.client_rate)}</Fact>
          <Fact label="Amount"><span className="font-semibold">{full(v.amount)}</span></Fact>
          <Fact label="Our cost">{v.cost_estimate ? full(v.cost_estimate) : <span className="text-muted-foreground">not priced</span>}</Fact>
          {v.margin !== null && <Fact label="Margin"><Pill tone={marginTone(v)} size="xs">{full(v.margin)} · {Number(v.margin_pct)}%</Pill></Fact>}
          {v.days_added ? <Fact label="Time added">{v.days_added} days</Fact> : null}
        </Facts>
      </SheetSection>

      <SheetSection title="So far" className="border-t">
        <ol className="flex flex-col">
          {steps.map((st, n) => (
            <li key={st.label} className="relative flex gap-3 pb-3 last:pb-0">
              {n < steps.length - 1 && <span className="absolute top-3 bottom-0 left-[5px] w-px bg-border" aria-hidden />}
              <span className={cn('relative mt-1 size-[11px] shrink-0 rounded-full border-2', st.done ? cn(TONE[st.tone].dot, 'border-transparent') : 'border-muted-foreground/40 bg-card')} aria-hidden />
              <span className="flex min-w-0 flex-1 items-baseline justify-between gap-2 text-sm">
                <span className={cn('font-medium', !st.done && 'text-muted-foreground')}>{st.label}</span>
                {st.when && <span className="shrink-0 text-xs text-muted-foreground">{day(st.when)}</span>}
              </span>
            </li>
          ))}
        </ol>
        {v.decision_note && <p className="mt-3 rounded-lg bg-muted/60 px-3 py-2 text-sm">{v.decision_note}</p>}
      </SheetSection>

      {v.status === 'approved' && (
        <SheetSection title="Where it went" className="border-t">
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm" variant="outline"><Link to={`/projects/${v.project_id}/boq`}>On the BOQ</Link></Button>
            <Button asChild size="sm" variant="outline"><Link to={`/billing/ra-bills?project=${v.project_id}`}>RA bills</Link></Button>
          </div>
        </SheetSection>
      )}

      <SheetSection title="Recorded by" className="border-t">
        <ByLine name={v.created_by_name ?? undefined} detail={day(v.created_at)} />
      </SheetSection>

      {open && (
        <SheetFooter className="flex-row flex-wrap items-center gap-2 border-t px-5 py-3">
          {v.status === 'draft' && (
            <Button size="sm" className="gap-1.5" disabled={busy} onClick={() => onAct('send')}><Send className="size-3.5" /> Sent to client</Button>
          )}
          <Button size="sm" variant={v.status === 'sent' ? 'default' : 'outline'} className="gap-1.5" disabled={busy} onClick={() => onDecide('approve')}><Check className="size-3.5" /> Approved</Button>
          <Button size="sm" variant="outline" className="gap-1.5" disabled={busy} onClick={() => onDecide('reject')}><X className="size-3.5" /> Rejected</Button>
          <Button size="sm" variant="ghost" className="gap-1.5" onClick={onEdit}><Pencil className="size-3.5" /> Edit</Button>
          {v.status === 'draft'
            ? <Button size="sm" variant="ghost" className="ml-auto gap-1.5 text-muted-foreground" disabled={busy} onClick={onDelete}><Trash2 className="size-3.5" /> Remove</Button>
            : <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground" disabled={busy} onClick={() => onAct('cancel')}>Cancel it</Button>}
        </SheetFooter>
      )}
    </>
  )
}

function DecideDialog({ target, busy, onClose, onDecide }: { target: { v: Variation; how: 'approve' | 'reject' } | null; busy: boolean; onClose: () => void; onDecide: (body: { decided_by: string | null; decided_on: string; note: string | null }) => void }) {
  const [by, setBy] = React.useState('')
  const [on, setOn] = React.useState('')
  const [note, setNote] = React.useState('')
  React.useEffect(() => {
    if (target) { setBy(target.v.asked_by ?? ''); setOn(localIsoDate(appNow())); setNote('') }
  }, [target])
  const yes = target?.how === 'approve'
  return (
    <Dialog open={!!target} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">{yes ? 'The client approved it?' : 'The client said no?'}</DialogTitle>
          <DialogDescription>
            {target ? `${target.v.ref} · ${target.v.title} · ${full(target.v.amount)}` : ''}
          </DialogDescription>
        </DialogHeader>
        {yes && target && (
          <p className="rounded-lg bg-success-soft/60 px-3 py-2 text-sm">
            {target.v.kind === 'new'
              ? <>It goes on the BOQ as <b>{target.v.ref}</b>: {qty(target.v.quantity)} {target.v.unit} at {full(target.v.client_rate)}, billed as the site does it.</>
              : <>{target.v.line?.work} grows by <b>{qty(target.v.quantity)} {target.v.unit}</b>.</>}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3 py-2 text-sm">
          <label className="space-y-1">
            <span className="font-medium">Who at the client</span>
            <Input value={by} onChange={(e) => setBy(e.target.value)} placeholder="Mr. Thomas" className="h-9" />
          </label>
          <div className="space-y-1">
            <span className="font-medium">On</span>
            <DatePicker value={on} onChange={setOn} aria-label="The day the client answered" required />
          </div>
          <label className="col-span-2 space-y-1">
            <span className="font-medium">{yes ? 'How (optional)' : 'Why (optional)'}</span>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={yes ? 'Signed on the drawing, WhatsApp 18 Nov' : 'Too costly; will do it later'} className="h-9" />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Back</Button>
          <Button disabled={busy} variant={yes ? 'default' : 'secondary'} onClick={() => onDecide({ decided_by: by.trim() || null, decided_on: on, note: note.trim() || null })}>
            {busy ? 'Saving…' : yes ? 'Approved: put it on the BOQ' : 'Mark rejected'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function VariationDialog({ open, v, projectId, onClose, onSaved, onClosed }: { open: boolean; v: Variation | null; projectId?: string; onClose: () => void; onSaved: (v: Variation) => void; onClosed: () => void }) {
  const toast = useToast()
  const [project, setProject] = React.useState('')
  const [kind, setKind] = React.useState<VariationKind>('new')
  const [lineId, setLineId] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [unit, setUnit] = React.useState('sqm')
  const [quantity, setQuantity] = React.useState('')
  const [rate, setRate] = React.useState('')
  const [cost, setCost] = React.useState('')
  const [days, setDays] = React.useState('')
  const [askedBy, setAskedBy] = React.useState('')
  const [askedOn, setAskedOn] = React.useState('')
  const [send, setSend] = React.useState(false)
  React.useEffect(() => {
    if (!open) return
    setProject(v?.project_id ?? projectId ?? '')
    setKind(v?.kind ?? 'new'); setLineId(v?.line?.id ?? ''); setTitle(v?.title ?? ''); setDescription(v?.description ?? '')
    setUnit(v?.unit ?? 'sqm'); setQuantity(v ? String(Number(v.quantity)) : ''); setRate(v ? String(Number(v.client_rate)) : '')
    setCost(v?.cost_estimate ? String(Number(v.cost_estimate)) : ''); setDays(v?.days_added ? String(v.days_added) : '')
    setAskedBy(v?.asked_by ?? ''); setAskedOn(v?.asked_on ?? localIsoDate(appNow())); setSend(false)
  }, [open, v, projectId])

  const projects = useQuery({ queryKey: ['scope-projects'], queryFn: fetchProjects, staleTime: 60_000, enabled: open && !projectId && !v })
  const boq = useQuery({ queryKey: ['boq', project], queryFn: () => fetchBoq(project), enabled: open && !!project && kind === 'more' && !v })
  const lines = React.useMemo(() => (boq.data?.sections ?? []).flatMap((s) => s.lines.map((l) => ({ ...l, section: s.name }))), [boq.data])
  const line = lines.find((l) => l.id === lineId)
  React.useEffect(() => {
    if (line && !v) { setUnit(line.unit); if (!rate && line.client_rate) setRate(String(Number(line.client_rate))); if (!title) setTitle(`More ${line.work.toLowerCase()}`) }
  }, [line, v]) // eslint-disable-line react-hooks/exhaustive-deps

  const amount = Number(quantity) * Number(rate)
  const margin = cost ? amount - Number(cost) : null
  const save = useMutation({
    mutationFn: () => {
      const body: VariationInput = {
        kind, title: title.trim(), description: description.trim() || null, line_id: kind === 'more' ? lineId : null,
        unit: kind === 'new' ? unit.trim() : null, quantity, client_rate: rate || null, cost_estimate: cost || null,
        days_added: days ? Number(days) : null, asked_by: askedBy.trim() || null, asked_on: askedOn || null, send,
      }
      if (v) { const { unit: u, ...rest } = body; return updateVariation(v.id, v.kind === 'new' ? { ...rest, unit: u } : rest) }
      return createVariation(project, body)
    },
    onSuccess: (saved) => { toast.success(v ? `${saved.ref} saved` : `${saved.ref} recorded`, saved.status === 'sent' ? 'Marked as sent to the client.' : undefined); onSaved(saved) },
    onError: (err: unknown) => toast.error('Could not save it', apiErrorMessage(err)),
  })
  const ready = !!project && !!title.trim() && Number(quantity) > 0 && rate !== '' && (kind === 'new' ? !!unit.trim() : !!lineId || !!v)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-lg" onCloseAutoFocus={(e) => { e.preventDefault(); onClosed() }}>
        <form onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">{v ? `Edit ${v.ref}` : 'New variation'}</DialogTitle>
            <DialogDescription>Work the client asked for that is not in the contract.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3.5 py-4 text-sm">
            {!projectId && !v && (
              <label className="block space-y-1">
                <span className="font-medium">Project</span>
                <select value={project} onChange={(e) => { setProject(e.target.value); setLineId('') }} className="h-9 w-full rounded-md border bg-card px-2 text-sm" required>
                  <option value="">Pick a project</option>
                  {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
            )}
            {!v && (
              <div className="grid grid-cols-2 gap-2" role="group" aria-label="What kind of variation">
                {([['new', ListPlus, 'New item', 'Work not in the BOQ'], ['more', Layers, 'More of a BOQ line', 'Same work, more of it']] as const).map(([k, Icon, label, hint]) => (
                  <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)} className={cn('flex items-start gap-2 rounded-lg border p-2.5 text-left transition', kind === k ? 'border-foreground bg-foreground text-background' : 'hover:bg-muted/50')}>
                    <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span><span className="block font-medium">{label}</span><span className={cn('block text-xs', kind === k ? 'opacity-80' : 'text-muted-foreground')}>{hint}</span></span>
                  </button>
                ))}
              </div>
            )}
            {kind === 'more' && !v && (
              <label className="block space-y-1">
                <span className="font-medium">BOQ line</span>
                <select value={lineId} onChange={(e) => setLineId(e.target.value)} className="h-9 w-full rounded-md border bg-card px-2 text-sm" disabled={!project}>
                  <option value="">{project ? (boq.isLoading ? 'Loading the BOQ…' : 'Pick the line') : 'Pick a project first'}</option>
                  {lines.map((l) => <option key={l.id} value={l.id}>{l.boq_code ? `${l.boq_code} · ` : ''}{l.work} ({l.unit}){l.client_rate ? ` · ₹${Number(l.client_rate).toLocaleString('en-IN')}` : ''}</option>)}
                </select>
              </label>
            )}
            <label className="block space-y-1">
              <span className="font-medium">What the client asked for</span>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Extra balcony on the first floor" className="h-9" required />
            </label>
            <div className="grid grid-cols-3 gap-2">
              <label className="space-y-1">
                <span className="font-medium">Quantity</span>
                <Input type="number" min={0} step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="h-9" required />
              </label>
              <label className="space-y-1">
                <span className="font-medium">Unit</span>
                {kind === 'new' && (!v || v.kind === 'new')
                  ? <Input value={unit} onChange={(e) => setUnit(e.target.value)} list="vo-units" className="h-9" required />
                  : <Input value={unit} disabled className="h-9" />}
                <datalist id="vo-units">{UNITS.map((u) => <option key={u} value={u} />)}</datalist>
              </label>
              <label className="space-y-1">
                <span className="font-medium">Client rate ₹</span>
                <Input type="number" min={0} step="any" value={rate} onChange={(e) => setRate(e.target.value)} className="h-9" required />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1">
                <span className="font-medium">Our cost ₹ <span className="font-normal text-muted-foreground">(optional)</span></span>
                <Input type="number" min={0} step="any" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="For the margin" className="h-9" />
              </label>
              <label className="space-y-1">
                <span className="font-medium">Days added <span className="font-normal text-muted-foreground">(optional)</span></span>
                <Input type="number" min={0} value={days} onChange={(e) => setDays(e.target.value)} className="h-9" />
              </label>
            </div>
            {/* The price as it is typed: the amount and, with our cost, the margin. */}
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 px-3 py-2">
              <span className="text-muted-foreground">Amount</span>
              <span className="font-semibold tabular-nums">{amount > 0 ? full(amount) : '—'}</span>
              {margin !== null && amount > 0 && (
                <Pill tone={margin < 0 ? 'bad' : margin / amount < 0.15 ? 'attention' : 'good'} size="xs">margin {full(margin)} · {Math.round((margin / amount) * 1000) / 10}%</Pill>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="space-y-1">
                <span className="font-medium">Asked by</span>
                <Input value={askedBy} onChange={(e) => setAskedBy(e.target.value)} placeholder="Mr. Thomas" className="h-9" />
              </label>
              <div className="space-y-1">
                <span className="font-medium">Asked on</span>
                <DatePicker value={askedOn} onChange={setAskedOn} aria-label="The day the client asked" required />
              </div>
            </div>
            <label className="block space-y-1">
              <span className="font-medium">Details <span className="font-normal text-muted-foreground">(optional)</span></span>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} className="min-h-16 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm" placeholder="Size, drawing, finish" />
            </label>
            {!v && (
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} className="size-4 accent-foreground" />
                Already sent to the client
              </label>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!ready || save.isPending} className="font-semibold">{save.isPending ? 'Saving…' : v ? 'Save' : 'Record it'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
