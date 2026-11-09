import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpRight, CheckCheck, Clock, Inbox, Layers } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useToast } from '@/components/ui/toast-notification'
import { useScope } from '@/lib/ScopeContext'
import { usePageTitle } from '@/lib/page-title'
import { useReadOnly } from '@/lib/trial'
import { useIsMobile } from '@/hooks/use-mobile'
import { rupees } from '@/lib/expenses'
import { errorDetail } from '@/lib/site-day'
import { cn } from '@/lib/utils'
import {
  GROUP_LOOK,
  INBOX_KEY,
  KIND_LOOK,
  TONE_LOOK,
  actionsFor,
  batchAction,
  decide,
  fetchInbox,
  waited,
  type InboxAction,
  type InboxGroup,
  type InboxKind,
  type InboxRow,
} from '@/lib/approvals'

// GM-01 (plan docs/plans/gm-pm-plan.md, mockup in the plan): Site > Waiting for you. Every decision waiting for this
// person in one list, flagged first, then the oldest; each row with the one fact that decides it. The buttons call the
// module's own route (lib/approvals.ts decide), so who may decide and what happens next stay each module's rule.
// Keyboard: j / k move, a the main yes, r reject, o open the source page.

type Tab = 'all' | InboxKind
const KINDS: InboxKind[] = ['material_request', 'subcontract_bill', 'measurement', 'ra_bill', 'size_request']
const GROUPS: InboxGroup[] = ['flagged', 'older', 'recent']

export default function ApprovalsPage() {
  usePageTitle('Waiting for you')
  const { scope } = useScope()
  const isMobile = useIsMobile()
  const readOnly = useReadOnly()
  const projectId = scope.mode === 'portfolio' ? null : scope.projectId
  const { data, isLoading, isError } = useQuery({
    queryKey: [...INBOX_KEY, projectId],
    queryFn: () => fetchInbox(projectId),
    refetchInterval: 60_000,
  })
  const all = React.useMemo(() => data?.items ?? [], [data])
  const [tab, setTab] = React.useState<Tab>('all')
  const [selected, setSelected] = React.useState('')
  const [checked, setChecked] = React.useState<Set<string>>(new Set())
  const list = React.useMemo(() => all.filter((r) => tab === 'all' || r.kind === tab), [all, tab])
  const current = list.find((r) => r.key === selected) ?? (isMobile ? undefined : list[0])

  const qc = useQueryClient()
  const toast = useToast()
  const after = React.useCallback(() => {
    void qc.invalidateQueries({ queryKey: INBOX_KEY })
    void qc.invalidateQueries({ queryKey: ['approvals-count'] })
  }, [qc])

  const batch = useMutation({
    mutationFn: async (rows: InboxRow[]) => {
      let done = 0
      for (const row of rows) {
        const act = batchAction(row)
        if (!act) continue
        await decide(row, act.action)
        done += 1
      }
      return done
    },
    onSuccess: (n) => { setChecked(new Set()); toast.success(`${n} done`, 'Each through its own page, as if decided there.'); after() },
    onError: (e) => { toast.error('Some were not done', errorDetail(e) ?? 'Refresh and try the rest.'); after() },
  })

  // j / k / o here; a / r in the detail panel (it owns the reason field).
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest('input, textarea, [contenteditable]')) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const i = current ? list.findIndex((r) => r.key === current.key) : -1
      if (e.key === 'j' && i < list.length - 1) { e.preventDefault(); setSelected(list[i + 1].key) }
      if (e.key === 'k' && i > 0) { e.preventDefault(); setSelected(list[i - 1].key) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [list, current])

  const counts = data?.counts
  const batchable = list.filter((r) => checked.has(r.key) && batchAction(r))
  const tiles = [
    { label: 'Waiting for you', value: counts?.total ?? 0, icon: Inbox, tone: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200' },
    { label: 'Flagged by a check', value: counts?.flagged ?? 0, icon: AlertTriangle, tone: 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-200' },
    { label: 'Waiting over 2 days', value: counts?.older ?? 0, icon: Clock, tone: 'bg-draft-soft text-draft' },
  ]

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 pb-24 sm:px-2 md:pb-8">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
            <Inbox className="size-5" />
          </span>
          <div>
            <div className="text-xs text-muted-foreground">Site</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Waiting for you</h1>
          </div>
        </div>
        <div className="hidden items-center gap-3 text-xs text-muted-foreground lg:flex">
          <span><Kbd>j</Kbd> <Kbd>k</Kbd> move</span><span><Kbd>a</Kbd> yes</span><span><Kbd>r</Kbd> reject</span><span><Kbd>o</Kbd> open</span>
        </div>
      </header>

      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {tiles.map((t) => (
          <div key={t.label} className="flex flex-col items-center gap-1 rounded-xl border bg-card p-2 text-center sm:flex-row sm:gap-3 sm:p-3.5 sm:text-left">
            <span className={cn('inline-flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-11 sm:rounded-xl', t.tone)}>
              <t.icon className="size-4 sm:size-5" />
            </span>
            <span className="flex flex-col">
              <span className="text-xl leading-none font-semibold tabular-nums sm:text-3xl">{isLoading ? '–' : t.value}</span>
              <span className="text-[11px] leading-tight text-muted-foreground sm:text-sm sm:text-foreground/80">{t.label}</span>
            </span>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Kind" className="flex max-w-full gap-0.5 overflow-x-auto rounded-xl bg-muted p-1">
          {(['all', ...KINDS] as Tab[]).filter((t) => t === 'all' || (counts?.[t] ?? 0) > 0).map((t) => {
            const on = tab === t
            const n = t === 'all' ? counts?.total ?? 0 : counts?.[t] ?? 0
            return (
              <button key={t} role="tab" type="button" aria-selected={on} onClick={() => setTab(t)}
                className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm whitespace-nowrap', on ? 'bg-background font-semibold shadow-sm' : 'text-foreground/75 hover:text-foreground')}>
                {t === 'all' ? 'All' : KIND_LOOK[t].plural}
                <span className={cn('rounded-full px-1.5 text-[11px] font-semibold tabular-nums', on ? 'bg-foreground text-background' : 'bg-background/70')}>{n}</span>
              </button>
            )
          })}
        </div>
        {checked.size > 0 && (
          <Button className="gap-2" disabled={readOnly || batch.isPending || !batchable.length} onClick={() => batch.mutate(batchable)}>
            <CheckCheck className="size-4" /> Confirm {batchable.length} selected
          </Button>
        )}
      </div>

      <div className="flex flex-col items-start gap-5 lg:flex-row">
        <section aria-label="Waiting for you" className="w-full min-w-0 flex-1 overflow-hidden rounded-xl border">
          {isLoading && <div className="flex flex-col">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse border-b bg-muted/40" />)}</div>}
          {isError && <p className="p-6 text-sm text-destructive">The list did not load. Refresh to try again.</p>}
          {!isLoading && !isError && list.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-14 text-center text-sm text-muted-foreground">
              <CheckCheck className="size-8 opacity-40" />
              Nothing is waiting for you{projectId ? ' on this project' : ''}.
              <span className="max-w-sm text-xs">Material requests, subcontract bills, work to confirm, RA bills and unit sizes come here when they need your decision.</span>
            </div>
          )}
          {GROUPS.map((g) => {
            const rows = list.filter((r) => r.group === g)
            if (!rows.length) return null
            return (
              <div key={g}>
                <div className="border-b bg-muted/50 px-4 py-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                  {GROUP_LOOK[g]} · {rows.length}
                </div>
                {rows.map((r) => (
                  <InboxRowView key={r.key} row={r} selected={current?.key === r.key} checked={checked.has(r.key)}
                    onPick={() => setSelected(r.key)}
                    onCheck={batchAction(r) && !readOnly ? (on) => setChecked((s) => { const n = new Set(s); if (on) n.add(r.key); else n.delete(r.key); return n }) : undefined} />
                ))}
              </div>
            )
          })}
        </section>

        {!isMobile && current && (
          <aside aria-label="Decision" className="sticky top-4 w-full shrink-0 overflow-hidden rounded-xl border bg-card lg:w-[420px]">
            <Detail key={current.key} row={current} readOnly={readOnly} keys onDone={after} />
          </aside>
        )}
      </div>

      {isMobile && (
        <Sheet open={!!current} onOpenChange={(o) => !o && setSelected('')}>
          <SheetContent side="bottom" className="max-h-[92vh] gap-0 overflow-y-auto rounded-t-2xl p-0">
            <SheetTitle className="sr-only">{current?.title ?? 'Decision'}</SheetTitle>
            {current && <Detail key={current.key} row={current} readOnly={readOnly} onDone={() => { setSelected(''); after() }} />}
          </SheetContent>
        </Sheet>
      )}
    </div>
  )
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-b-2 bg-background px-1.5 font-mono text-[11px]">{children}</kbd>
}

function where(row: InboxRow): string {
  return [row.project_name, row.site_name].filter(Boolean).join(' · ') || 'Whole company'
}

function InboxRowView({ row, selected, checked, onPick, onCheck }: {
  row: InboxRow; selected: boolean; checked: boolean; onPick: () => void; onCheck?: (on: boolean) => void
}) {
  return (
    <div role="button" tabIndex={0} onClick={onPick} onKeyDown={(e) => { if (e.key === 'Enter') onPick() }}
      className={cn('grid cursor-pointer grid-cols-[20px_minmax(0,1fr)_auto] items-start gap-3 border-b px-4 py-3 outline-none last:border-b-0 hover:bg-muted/40 focus-visible:bg-muted/60',
        selected && 'bg-yellow-50 hover:bg-yellow-50 dark:bg-yellow-950/40')}>
      <span className="pt-0.5" onClick={(e) => e.stopPropagation()}>
        {onCheck ? (
          <input type="checkbox" aria-label={`Select ${row.title}`} checked={checked} onChange={(e) => onCheck(e.target.checked)} className="size-4 accent-yellow-600" />
        ) : <span className="block size-4" />}
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={cn('rounded-full px-2 py-px text-[11px] font-medium', KIND_LOOK[row.kind].chip)}>{KIND_LOOK[row.kind].label}</span>
          {row.flagged && <span className="rounded-full bg-red-100 px-2 py-px text-[11px] font-medium text-red-800 dark:bg-red-950 dark:text-red-200">Check</span>}
          {row.ref && <span className="font-mono text-[11px] text-muted-foreground">{row.ref}</span>}
        </div>
        <div className="truncate font-semibold">{row.title}</div>
        <div className="truncate text-xs text-muted-foreground">{where(row)}{row.asked_by ? ` · ${row.asked_by}` : ''}</div>
        <div><span className={cn('inline-block rounded-md px-2 py-0.5 text-xs', TONE_LOOK[row.tone])}>{row.fact}</span></div>
      </div>
      <div className="flex flex-col items-end gap-1 text-right">
        {row.amount && <span className="font-mono text-sm tabular-nums">{row.extra.amount_is_estimate ? '~' : ''}{rupees(Number(row.amount))}</span>}
        <span className="text-[11px] text-muted-foreground">{waited(row.since)}</span>
      </div>
    </div>
  )
}

function Detail({ row, readOnly, keys, onDone }: { row: InboxRow; readOnly: boolean; keys?: boolean; onDone: () => void }) {
  const toast = useToast()
  const acts = actionsFor(row)
  const [asking, setAsking] = React.useState<InboxAction | null>(null)
  const [note, setNote] = React.useState(row.kind === 'size_request' ? String(row.extra.proposed_one_unit_equals ?? '') : '')
  const field = React.useRef<HTMLInputElement>(null)
  const go = useMutation({
    mutationFn: (x: { act: InboxAction; note?: string }) => decide(row, x.act.action, x.note),
    onSuccess: (_, x) => { toast.success(`${row.ref ?? row.title}: ${x.act.done}`); onDone() },
    onError: (e) => toast.error('Not done', errorDetail(e) ?? 'Refresh and try again.'),
  })
  const press = React.useCallback((act: InboxAction) => {
    if (readOnly || go.isPending) return
    if (act.reason || act.number) { setAsking(act); setTimeout(() => field.current?.focus(), 0); return }
    go.mutate({ act })
  }, [readOnly, go])

  React.useEffect(() => {
    if (!keys) return
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest('input, textarea, [contenteditable]')) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'a') { const p = acts.find((a) => a.primary) ?? acts[0]; if (p) { e.preventDefault(); press(p) } }
      if (e.key === 'r') { const d = acts.find((a) => a.danger); if (d) { e.preventDefault(); press(d) } }
      if (e.key === 'o') { e.preventDefault(); window.location.assign(row.link) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [keys, acts, press, row.link])

  const lines = (row.extra.lines as { material?: string; description?: string; quantity: string; unit: string; at_site?: string; to_buy?: string; rate?: string; agreed_rate?: string }[] | undefined) ?? []
  const flags = (row.extra.flags as string[] | undefined) ?? []
  const missing = asking && ((asking.reason === 'required' && note.trim().length < 2) || (asking.number && !(Number(note) > 0)))

  return (
    <div className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={cn('rounded-full px-2 py-px text-xs font-medium', KIND_LOOK[row.kind].chip)}>{KIND_LOOK[row.kind].label}</span>
        {row.flagged && <span className="rounded-full bg-red-100 px-2 py-px text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-200">Needs a check</span>}
      </div>
      <h2 className="text-lg leading-snug font-semibold">{row.title}</h2>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Where</dt><dd>{where(row)}</dd>
        {row.asked_by && <><dt className="text-muted-foreground">From</dt><dd>{row.asked_by}</dd></>}
        {row.amount && <><dt className="text-muted-foreground">{row.extra.amount_is_estimate ? 'About' : 'Amount'}</dt><dd className="font-mono tabular-nums">{rupees(Number(row.amount))}{row.extra.amount_is_estimate ? ' at the last rates' : ''}</dd></>}
        <dt className="text-muted-foreground">Waiting</dt><dd>{waited(row.since)}</dd>
        {typeof row.extra.needed_by === 'string' && <><dt className="text-muted-foreground">Needed by</dt><dd>{row.extra.needed_by}</dd></>}
      </dl>

      <div className="flex flex-col gap-2 rounded-xl border bg-muted/30 p-3">
        <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">What decides it</div>
        <div className={cn('rounded-md px-2.5 py-1.5 text-sm', TONE_LOOK[row.tone])}>{row.fact}</div>
        {flags.length > 1 && <ul className="list-disc pl-5 text-sm">{flags.map((f) => <li key={f}>{f}</li>)}</ul>}
        {lines.length > 0 && (
          <table className="w-full text-sm">
            <tbody>
              {lines.map((l, i) => (
                <tr key={i} className="border-t first:border-t-0">
                  <td className="py-1 pr-2">{l.material ?? l.description}</td>
                  <td className="py-1 text-right font-mono tabular-nums">{l.quantity} {l.unit}</td>
                  {l.to_buy !== undefined && <td className="py-1 pl-2 text-right text-xs text-muted-foreground">{l.at_site} at site</td>}
                  {l.rate !== undefined && <td className={cn('py-1 pl-2 text-right text-xs', l.agreed_rate && Number(l.rate) > Number(l.agreed_rate) ? 'text-red-700 dark:text-red-300' : 'text-muted-foreground')}>₹{l.rate}{l.agreed_rate && l.agreed_rate !== l.rate ? ` (agreed ₹${l.agreed_rate})` : ''}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {asking && (
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (!missing) go.mutate({ act: asking, note: note.trim() }) }}>
          <label htmlFor={`note-${row.key}`} className="text-sm font-medium">
            {asking.number ? `1 ${String(row.extra.unit)} of ${String(row.extra.material)} is how many ${String(row.extra.stock_unit ?? '')}?`
              : asking.reason === 'required' ? 'Why? (they are told)' : 'Note (optional)'}
          </label>
          <Input id={`note-${row.key}`} ref={field} value={note} onChange={(e) => setNote(e.target.value)} inputMode={asking.number ? 'decimal' : 'text'}
            placeholder={asking.number ? '150' : asking.action === 'sent' ? 'From which site' : asking.danger ? 'Only 200 sqm done' : 'Checked on site'} />
          <div className="flex gap-2">
            <Button type="submit" variant={asking.danger ? 'destructive' : 'default'} disabled={!!missing || go.isPending}>{asking.label}</Button>
            <Button type="button" variant="ghost" onClick={() => setAsking(null)}>Back</Button>
          </div>
        </form>
      )}

      {!asking && (
        <div className="flex flex-wrap gap-2">
          {acts.map((a) => (
            <Button key={a.action} variant={a.danger ? 'outline' : a.primary ? 'default' : 'outline'} disabled={readOnly || go.isPending}
              className={cn(a.danger && 'border-destructive/30 text-destructive')} onClick={() => press(a)}>
              {a.label}
            </Button>
          ))}
        </div>
      )}

      <Link to={row.link} className="inline-flex items-center gap-1 text-sm font-medium text-primary-ink hover:underline">
        Open the full page <ArrowUpRight className="size-3.5" />
      </Link>
      {row.kind === 'material_request' && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground"><Layers className="mt-0.5 size-3.5 shrink-0" />To raise a purchase order for it, open the full page.</p>
      )}
    </div>
  )
}
