import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, CheckCircle2, Clock, Flame, Stamp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { EmptyState, PageError } from '@/components/page/page-kit'
import { ModuleHeader } from '@/components/page/module-header'
import { FilterSelect } from '@/components/filter-select'
import { DecideDialog } from '@/components/subcontracts/dialogs'
import { RequestDetail } from '@/components/requests/request-detail'
import {
  KIND_LABEL,
  KIND_LOOK,
  KIND_ORDER,
  bulkApprovable,
  confirmSiteDay,
  daysWaited,
  itemKey,
  fetchWaiting,
  waitedFor,
  waitingUrl,
  type Waiting,
  type WaitingItem,
  type WaitingKind,
} from '@/lib/approvals'
import { fetchBillsWaiting, type WoBill } from '@/lib/subcontracts'
import { approveWageSheet } from '@/lib/labour-pay'
import { moveTask } from '@/lib/tasks'
import { fetchRequest } from '@/lib/requests'
import { apiErrorMessage } from '@/lib/logo-upload'
import { rupees } from '@/lib/accounts'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { cn } from '@/lib/utils'

// UX-62: Approvals, everything waiting on this person in one place (the NXT-08 inbox, GET /approvals/waiting, which
// reads each module's own list as the caller). Urgent first, then today, then older; a coloured tile per kind; the
// simple decisions are taken right on the row with each module's own action (a subcontractor's bill, a week's wages,
// a task); a material request opens its own panel (order it, send it from another site, or say no); the rest open
// the record where it is checked line by line.
// FB-02 (contractor session, 21 Nov: "100 labour entries across 10 sites take 300 clicks"): a site's day is confirmed
// with one tap (every entry on it), and the rows that need nothing opened (site days, draft wage weeks) can be ticked,
// or all selected, and approved together. Bills, requests and counts stay one by one: each has figures to check.

type KindFilter = 'all' | WaitingKind

export default function ApprovalsPage() {
  usePageTitle('Approvals')
  const query = useQuery({ queryKey: ['approvals', 'waiting'], queryFn: fetchWaiting, refetchInterval: 60_000, staleTime: 15_000 })
  const [kind, setKind] = useUrlState<KindFilter>('kind', 'all')
  const [project, setProject] = useUrlState<string>('project_name', 'all')
  const [urgentOnly, setUrgentOnly] = useUrlState<'' | '1'>('urgent', '')
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set())

  const header = (
    <ModuleHeader
      icon={Stamp}
      title="Approvals"
      chip={query.data && query.data.total > 0 ? <HeaderChips data={query.data} /> : undefined}
    >
      {query.data && query.data.items.length > 0 && (
        <>
          <ProjectFilter items={query.data.items} value={project} onChange={setProject} />
          <button
            type="button"
            aria-pressed={urgentOnly === '1'}
            onClick={() => setUrgentOnly(urgentOnly === '1' ? '' : '1')}
            className={cn('inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold shadow-xs',
              urgentOnly === '1' ? 'border-rose-500 bg-rose-500 text-white' : 'bg-card hover:bg-muted')}
            data-guide="approvals.urgent"
          >
            <Flame className="size-3.5" />Urgent only
          </button>
        </>
      )}
    </ModuleHeader>
  )

  if (query.isError) return <div className="flex flex-col gap-4">{header}<PageError message="The list did not load." onRetry={() => query.refetch()} back={{ to: '/today', label: 'Today' }} /></div>
  if (!query.data) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <Skeleton className="h-12 w-full" />
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[72px] w-full" />)}
      </div>
    )
  }
  const data = query.data
  const inProject = data.items.filter((i) => project === 'all' || (i.project_name ?? '') === project)
  const shown = inProject.filter((i) => (kind === 'all' || i.kind === kind) && (urgentOnly !== '1' || i.urgent))

  return (
    <div className="flex flex-col gap-4">
      {header}
      {data.unavailable.length > 0 && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Could not check {data.unavailable.map((k) => KIND_LABEL[k].toLowerCase()).join(', ')} just now.
        </p>
      )}
      {data.total === 0 ? (
        <EmptyState icon={CheckCircle2} title="All clear" about="Nothing is waiting on you." className="bg-card" />
      ) : (
        <>
          <KindChips items={inProject} value={kind} onChange={setKind} />
          {shown.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="Nothing here" action={<Button variant="outline" size="sm" onClick={() => { setKind('all'); setUrgentOnly(''); setProject('all') }}>Show all</Button>} className="bg-card" />
          ) : (
            <>
              <BulkBar items={shown} selected={selected} setSelected={setSelected} />
              <Groups items={shown} today={data.today} selected={selected} setSelected={setSelected} />
            </>
          )}
          {data.items.length < data.total && <p className="text-xs text-muted-foreground">Showing the first {data.items.length} of {data.total}.</p>}
        </>
      )}
    </div>
  )
}

function HeaderChips({ data }: { data: Waiting }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="rounded-full bg-orange-500 px-2 py-0.5 text-xs font-semibold text-white tabular-nums">{data.total} waiting</span>
      {data.urgent > 0 && <span className="rounded-full bg-rose-500 px-2 py-0.5 text-xs font-semibold text-white tabular-nums">{data.urgent} urgent</span>}
    </span>
  )
}

function ProjectFilter({ items, value, onChange }: { items: WaitingItem[]; value: string; onChange: (v: string) => void }) {
  const names = [...new Set(items.map((i) => i.project_name).filter((n): n is string => !!n))].sort()
  if (names.length < 2) return null
  return (
    <FilterSelect
      label="Project"
      value={names.includes(value) ? value : 'all'}
      onChange={onChange}
      options={[{ value: 'all', label: 'All projects' }, ...names.map((n) => ({ value: n, label: n }))]}
      className="w-[180px] bg-card shadow-xs"
    />
  )
}

/** A filter tile per kind that has something waiting: its icon, colour and count (red dot: some are urgent). */
function KindChips({ items, value, onChange }: { items: WaitingItem[]; value: KindFilter; onChange: (k: KindFilter) => void }) {
  const kinds = KIND_ORDER.filter((k) => items.some((i) => i.kind === k))
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Kind" data-guide="approvals.kinds">
      <Chip active={value === 'all'} onClick={() => onChange('all')} label="All" n={items.length} urgent={items.some((i) => i.urgent)} />
      {kinds.map((k) => {
        const mine = items.filter((i) => i.kind === k)
        return <Chip key={k} kind={k} active={value === k} onClick={() => onChange(value === k ? 'all' : k)} label={KIND_LOOK[k].short} n={mine.length} urgent={mine.some((i) => i.urgent)} />
      })}
    </div>
  )
}

function Chip({ kind, active, onClick, label, n, urgent }: { kind?: WaitingKind; active: boolean; onClick: () => void; label: string; n: number; urgent: boolean }) {
  const look = kind ? KIND_LOOK[kind] : null
  const Icon = look?.icon
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn('relative inline-flex h-9 items-center gap-2 rounded-lg border bg-card pr-3 pl-1.5 text-sm font-medium shadow-xs transition-colors',
        active ? 'border-foreground ring-1 ring-foreground' : 'hover:bg-muted', !look && 'pl-3')}
    >
      {Icon && <span className={cn('flex size-6 items-center justify-center rounded-md', look.tile)}><Icon className="size-3.5" /></span>}
      {label}
      <span className="rounded-full bg-muted px-1.5 text-xs font-semibold tabular-nums">{n}</span>
      {urgent && <span aria-label="some urgent" className="absolute -top-1 -right-1 size-2.5 rounded-full bg-rose-500 ring-2 ring-background" />}
    </button>
  )
}

type Selection = { selected: Set<string>; setSelected: React.Dispatch<React.SetStateAction<Set<string>>> }

/** FB-02: tick rows (or all) that need nothing opened and approve them together, each with its module's own action. */
function BulkBar({ items, selected, setSelected }: { items: WaitingItem[] } & Selection) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const can = items.filter(bulkApprovable)
  const picked = can.filter((i) => selected.has(itemKey(i)))
  const all = can.length > 0 && picked.length === can.length
  const run = useMutation({
    mutationFn: async (rows: WaitingItem[]) => {
      let ok = 0
      let entries = 0
      const failed: string[] = []
      for (const item of rows) {
        try {
          if (item.kind === 'site_report') {
            const n = (await confirmSiteDay(item.site_id!, item.date!)).confirmed
            if (n === 0) { failed.push(`${item.title}: nothing was left to confirm`); continue }
            entries += n
          } else await approveWageSheet(item.id)
          ok += 1
        } catch (e) {
          failed.push(`${item.title}: ${apiErrorMessage(e)}`)
        }
      }
      return { ok, entries, failed }
    },
    onSuccess: ({ ok, entries, failed }) => {
      if (ok) toast.success(`${ok} approved`, entries ? `${entries} site entr${entries === 1 ? 'y' : 'ies'} confirmed` : undefined)
      if (failed.length) toast.error(`${failed.length} not approved`, failed.slice(0, 3).join(' · '))
      setSelected(new Set())
      for (const k of ['approvals', 'labour', 'dpr']) queryClient.invalidateQueries({ queryKey: [k] })
    },
  })
  if (can.length < 2) return null
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card px-3 py-2 shadow-xs" data-guide="approvals.bulk">
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          className="size-4 accent-foreground"
          checked={all}
          ref={(el) => { if (el) el.indeterminate = picked.length > 0 && !all }}
          onChange={() => setSelected(all ? new Set() : new Set(can.map(itemKey)))}
        />
        Select all {can.length} that need nothing opened
      </label>
      <Button size="sm" className="gap-1.5" disabled={picked.length === 0 || run.isPending} onClick={() => run.mutate(picked)}>
        <Check className="size-3.5" />{run.isPending ? 'Approving…' : `Approve ${picked.length || ''}`.trim()}
      </Button>
    </div>
  )
}

function Groups({ items, today, selected, setSelected }: { items: WaitingItem[]; today: string } & Selection) {
  const groups = [
    { key: 'urgent', title: 'Urgent', icon: Flame, tone: 'text-rose-600 dark:text-rose-400', items: items.filter((i) => i.urgent) },
    { key: 'today', title: 'Today', icon: Clock, tone: 'text-foreground', items: items.filter((i) => !i.urgent && daysWaited(i.since, today) === 0) },
    { key: 'older', title: 'Waiting longer', icon: Clock, tone: 'text-muted-foreground', items: items.filter((i) => !i.urgent && daysWaited(i.since, today) > 0) },
  ].filter((g) => g.items.length)
  return (
    <div className="flex flex-col gap-5" data-guide="approvals.list">
      {groups.map((g) => (
        <section key={g.key} className="flex flex-col gap-2">
          <h2 className={cn('flex items-center gap-1.5 text-sm font-semibold', g.tone)}>
            <g.icon className="size-4" />{g.title}<span className="font-normal text-muted-foreground tabular-nums">{g.items.length}</span>
          </h2>
          <ul className="flex flex-col overflow-hidden rounded-xl border bg-card shadow-xs">
            {g.items.map((item) => <Row key={itemKey(item)} item={item} today={today} selected={selected} setSelected={setSelected} />)}
          </ul>
        </section>
      ))}
    </div>
  )
}

function Row({ item, today, selected, setSelected }: { item: WaitingItem; today: string } & Selection) {
  const look = KIND_LOOK[item.kind]
  const Icon = look.icon
  const where = [item.project_name, item.site_name].filter(Boolean).join(' · ')
  const days = daysWaited(item.since, today)
  const amount = item.amount != null && Number(item.amount) !== 0 ? Number(item.amount) : null
  return (
    <li
      data-record-id={item.id}
      className={cn('relative flex flex-col gap-3 border-b px-4 py-3 last:border-b-0 sm:flex-row sm:items-center',
        item.urgent && 'before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-rose-500')}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        {bulkApprovable(item) && (
          <input
            type="checkbox"
            aria-label={`Select ${item.title}`}
            className="mt-2.5 size-4 shrink-0 accent-foreground"
            checked={selected.has(itemKey(item))}
            onChange={() => setSelected((s) => { const n = new Set(s); const k = itemKey(item); if (n.has(k)) n.delete(k); else n.add(k); return n })}
          />
        )}
        <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-lg', look.tile)} title={KIND_LABEL[item.kind]}>
          <Icon className="size-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="truncate font-semibold">{item.title}</span>
            {amount != null && <span className="text-sm font-semibold tabular-nums">{amount < 0 ? '−' : ''}{rupees(amount)}</span>}
          </div>
          {item.detail && <div className="truncate text-sm text-muted-foreground">{item.detail}</div>}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs">
            {where && <span className="truncate rounded-full bg-muted px-2 py-0.5">{where}</span>}
            {item.since && (
              <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium tabular-nums',
                item.urgent ? 'bg-rose-500/10 text-rose-700 dark:text-rose-300' : waitTone(days))}>
                <Clock className="size-3" />{waitedFor(item.since, today)}
              </span>
            )}
          </div>
        </div>
      </div>
      <Actions item={item} />
    </li>
  )
}

/** How long a row has waited, by colour: today grey, 3 days amber, a week red. */
function waitTone(days: number): string {
  return days >= 7 ? 'bg-destructive/10 text-destructive' : days >= 3 ? 'bg-draft-soft text-draft' : 'bg-muted text-muted-foreground'
}

/** The row's buttons: the module's own one-tap decision where there is one, and always a way to the record. */
function Actions({ item }: { item: WaitingItem }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [bill, setBill] = React.useState<{ bill: WoBill; decision: 'approve' | 'reject' } | null>(null)
  const [requestOpen, setRequestOpen] = React.useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['approvals'] })

  const act = useMutation({
    mutationFn: async (what: 'wages' | 'task' | 'approve' | 'reject' | 'day') => {
      if (what === 'day') return confirmSiteDay(item.site_id!, item.date!)
      if (what === 'wages') return approveWageSheet(item.id)
      if (what === 'task') return moveTask(item.id, 'done')
      // A subcontractor's bill: the same bill the module lists, so its dialog shows the check's flags.
      const found = (await fetchBillsWaiting()).find((b) => b.id === item.id)
      if (!found) throw new Error('This bill was decided already.')
      setBill({ bill: found, decision: what })
      return null
    },
    onSuccess: (result, what) => {
      if (what === 'wages') { toast.success('Wages approved', 'Pay them from the wages page.'); queryClient.invalidateQueries({ queryKey: ['labour'] }) }
      if (what === 'task') { toast.success('Task done'); queryClient.invalidateQueries({ queryKey: ['tasks'] }) }
      if (what === 'day') { const n = (result as { confirmed: number }).confirmed; toast.success(`${n} entr${n === 1 ? 'y' : 'ies'} confirmed`); queryClient.invalidateQueries({ queryKey: ['dpr'] }) }
      if (result !== null) refresh()
    },
    onError: (err) => { toast.error('Not saved', err instanceof Error && !('response' in err) ? err.message : apiErrorMessage(err)); refresh() },
  })

  const open = (label: string) => (
    <Button asChild variant="outline" size="sm" className="h-9 sm:h-8">
      <Link to={waitingUrl(item)}>{label}<ArrowRight className="size-3.5" /></Link>
    </Button>
  )
  const busy = act.isPending

  let buttons: React.ReactNode
  switch (item.kind) {
    case 'subcontract_bill':
      buttons = (
        <>
          <Button size="sm" className="h-9 flex-1 sm:h-8 sm:flex-none" disabled={busy} onClick={() => act.mutate('approve')}><Check className="size-3.5" />Approve</Button>
          <Button size="sm" variant="outline" className="h-9 flex-1 text-destructive sm:h-8 sm:flex-none" disabled={busy} onClick={() => act.mutate('reject')}><X className="size-3.5" />Reject</Button>
          {open('Open')}
        </>
      )
      break
    case 'wage_sheet': {
      const draft = (item.detail ?? '').startsWith('Draft')
      buttons = draft ? (
        <>
          <Button size="sm" className="h-9 flex-1 sm:h-8 sm:flex-none" disabled={busy} onClick={() => act.mutate('wages')}><Check className="size-3.5" />Approve</Button>
          {open('Check')}
        </>
      ) : open('Pay')
      break
    }
    case 'task':
      buttons = (
        <>
          <Button size="sm" className="h-9 flex-1 sm:h-8 sm:flex-none" disabled={busy} onClick={() => act.mutate('task')}><Check className="size-3.5" />Done</Button>
          {open('Open')}
        </>
      )
      break
    case 'material_request':
      buttons = (
        <>
          <Button size="sm" className="h-9 flex-1 sm:h-8 sm:flex-none" onClick={() => setRequestOpen(true)}>Decide</Button>
          {open('Open')}
        </>
      )
      break
    case 'site_report':
      buttons = item.site_id && item.date ? (
        <>
          <Button size="sm" className="h-9 flex-1 sm:h-8 sm:flex-none" disabled={busy} onClick={() => act.mutate('day')}><Check className="size-3.5" />Confirm all</Button>
          {open('Check')}
        </>
      ) : open('Confirm')
      break
    case 'labour_split':
      buttons = open('Check')
      break
    default:
      buttons = open('Review')
  }

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
      {buttons}
      {bill && <DecideDialog bill={bill.bill} decision={bill.decision} onOpenChange={(o) => { if (!o) { setBill(null); refresh() } }} />}
      {item.kind === 'material_request' && <RequestSheet id={item.id} open={requestOpen} onOpenChange={(o) => { setRequestOpen(o); if (!o) refresh() }} />}
    </div>
  )
}

/** A material request decided in its own panel (Requests' own detail: order it, send from another site, or no). */
function RequestSheet({ id, open, onOpenChange }: { id: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const query = useQuery({ queryKey: ['procurement', 'requests', 'one', id], queryFn: () => fetchRequest(id), enabled: open })
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-[460px]">
        <SheetHeader className="sr-only">
          <SheetTitle>{query.data?.ref ?? 'Material request'}</SheetTitle>
          <SheetDescription>Decide this request</SheetDescription>
        </SheetHeader>
        {query.data ? <RequestDetail request={query.data} inSheet /> : query.isError ? <p className="p-5 text-sm">{apiErrorMessage(query.error)}</p> : <div className="p-5"><Skeleton className="h-40 w-full" /></div>}
      </SheetContent>
    </Sheet>
  )
}
