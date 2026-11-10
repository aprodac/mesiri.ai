import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, CheckCircle2, ClipboardList, Play, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ModuleTitle } from '@/components/page/page-kit'
import { useScope } from '@/lib/ScopeContext'
import { useAuth } from '@/lib/AuthContext'
import { usePageTitle } from '@/lib/page-title'
import { useUrlState } from '@/lib/url-state'
import { useReadOnly } from '@/lib/trial'
import { useSiteNames } from '@/lib/site-names'
import { rupees } from '@/lib/orders'
import { COUNT_REASONS, approveCount, cancelCount, fetchCount, fetchCounts, saveCountLines, startCount, type CountLine, type CountReason, type StockCount } from '@/lib/stock-count'
import { cn } from '@/lib/utils'

// PRC-48: Materials › Stock count. Start a count for a site (all items, one category, or the 20 most valuable): the
// book is frozen. The count sheet is built for a phone at the site -- big inputs, grouped by category, save part of it
// and come back, leave an item empty for "not counted". Review shows book vs counted and the difference in units and
// rupees (largest first); each difference needs a reason; the owner or admin approves it into the ledger. An approved
// count is never changed: a new count corrects it. Sites not counted in 30 days are listed as due.

const n = (v: string | null) => (v === null ? '' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 }))
const detail = (err: unknown, fallback: string) => {
  const d = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

export default function StockCountPage() {
  usePageTitle('Stock count')
  const { scope } = useScope()
  const { me } = useAuth()
  const readOnly = useReadOnly()
  const siteNames = useSiteNames()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useUrlState<string>('id', '')
  const [startSite, setStartSite] = React.useState(scope.mode === 'site' ? scope.siteId : '')
  const [startScope, setStartScope] = React.useState<'all' | 'top'>('all')
  const [error, setError] = React.useState('')
  const list = useQuery({ queryKey: ['materials', 'stock-counts'], queryFn: fetchCounts })
  const canCount = !!me && me.role.toUpperCase() !== 'FINANCE' && !readOnly
  const start = useMutation({
    mutationFn: () => startCount({ site_id: startSite, scope: startScope }),
    onSuccess: (c) => { queryClient.invalidateQueries({ queryKey: ['materials', 'stock-counts'] }); setSelected(c.id) },
    onError: (err) => setError(detail(err, 'The count did not start.')),
  })
  const counts = list.data?.items ?? []
  const open = counts.find((c) => c.id === selected)
  const sites = [...siteNames.entries()].map(([id, s]) => ({ id, label: `${s.project} › ${s.name}` })).sort((a, b) => a.label.localeCompare(b.label))

  return (
    <div className="mx-auto flex w-full flex-col gap-4 pb-8 sm:px-2">
      <header className="flex items-center justify-between gap-3">
        <ModuleTitle icon={ClipboardList} title="Stock count" />
      </header>

      {!!list.data?.due.length && (
        <section className="flex flex-col gap-1 rounded-xl border border-orange-300 bg-orange-50 p-3 text-sm dark:border-orange-800 dark:bg-orange-950/40">
          <span className="flex items-center gap-2 font-semibold"><AlarmClock className="size-4" /> Due for a count</span>
          {list.data.due.map((d) => (
            <button key={d.site_id} type="button" className="text-left hover:underline" onClick={() => setStartSite(d.site_id)}>
              {d.project_name} › {d.site_name}: {d.last_counted ? `last counted ${d.last_counted}` : 'never counted'}
            </button>
          ))}
        </section>
      )}

      {canCount && (
        <form className="flex flex-wrap items-end gap-2 rounded-xl border p-3" onSubmit={(e) => { e.preventDefault(); setError(''); start.mutate() }}>
          <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs font-semibold text-muted-foreground">
            Site
            <select value={startSite} onChange={(e) => setStartSite(e.target.value)} className="h-10 rounded-md border bg-background px-2 text-sm text-foreground">
              <option value="">Pick a site</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.label}{list.data?.last_counted[s.id] ? ` (counted ${list.data.last_counted[s.id]})` : ''}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-muted-foreground">
            What
            <select value={startScope} onChange={(e) => setStartScope(e.target.value as 'all' | 'top')} className="h-10 rounded-md border bg-background px-2 text-sm text-foreground">
              <option value="all">Every item</option>
              <option value="top">The 20 most valuable</option>
            </select>
          </label>
          <Button type="submit" className="h-10 gap-2 font-semibold" disabled={!startSite || start.isPending}><Play className="size-4" /> Start count</Button>
          {error && <p className="w-full text-sm text-destructive">{error}</p>}
        </form>
      )}

      <div className="flex flex-col items-start gap-4 lg:flex-row">
        <ul className="w-full divide-y overflow-hidden rounded-xl border lg:max-w-sm">
          {list.isLoading && <li className="h-16 animate-pulse bg-muted/40" />}
          {!list.isLoading && counts.length === 0 && <li className="p-6 text-center text-sm text-muted-foreground"><strong className="block text-foreground">Book stock drifts from real stock.</strong>Count a site once a month: the differences show in rupees, and approving them puts the book right.</li>}
          {counts.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => setSelected(c.id)} className={cn('flex w-full items-center gap-3 px-3 py-3 text-left hover:bg-muted/40', selected === c.id && 'bg-yellow-50 dark:bg-yellow-950/40')}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{c.ref} · {c.site_name}</span>
                  <span className="block text-xs text-muted-foreground">{c.counts.counted} of {c.counts.lines} counted · {c.counts.differing} differ{c.net_value ? ` · ${rupees(c.net_value)}` : ''}</span>
                </span>
                <span className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', c.status === 'open' ? 'bg-yellow-100 text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100' : c.status === 'approved' ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' : 'bg-muted text-muted-foreground')}>
                  {c.status === 'open' ? 'Counting' : c.status === 'approved' ? 'Approved' : 'Cancelled'}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {open && <CountSheet key={open.id} id={open.id} />}
      </div>
    </div>
  )
}

type Draft = Record<string, { counted: string; reason: CountReason | '' }>

function CountSheet({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const { data: c } = useQuery({ queryKey: ['materials', 'stock-counts', id], queryFn: () => fetchCount(id) })
  const [draft, setDraft] = React.useState<Draft>({})
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    if (c?.lines) setDraft(Object.fromEntries(c.lines.map((l) => [l.material_id, { counted: l.counted ?? '', reason: l.reason ?? '' }])))
  }, [c])
  const refresh = (got: StockCount) => {
    queryClient.setQueryData(['materials', 'stock-counts', id], got)
    queryClient.invalidateQueries({ queryKey: ['materials'] })
    setError('')
  }
  const save = useMutation({
    mutationFn: () => saveCountLines(id, Object.entries(draft).map(([material_id, d]) => ({ material_id, counted: d.counted.trim() === '' ? null : d.counted.trim(), reason: d.reason || null }))),
    onSuccess: refresh,
    onError: (err) => setError(detail(err, 'Not saved.')),
  })
  const approve = useMutation({ mutationFn: () => approveCount(id), onSuccess: refresh, onError: (err) => setError(detail(err, 'Not approved.')) })
  const cancel = useMutation({ mutationFn: () => cancelCount(id, 'Not going on with it'), onSuccess: refresh })
  if (!c?.lines) return <div className="h-40 w-full animate-pulse rounded-xl bg-muted/40" />
  const groups = [...new Set(c.lines.map((l) => l.main_category))]
  const money = c.net_value !== undefined

  return (
    <section className="flex w-full min-w-0 flex-1 flex-col gap-3 rounded-xl border p-3 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{c.ref} · {c.site_name}</h2>
          <p className="text-xs text-muted-foreground">Book frozen {c.created_at.slice(0, 10)} · {c.counts.counted} of {c.counts.lines} counted{money && c.counts.differing ? ` · net ${rupees(c.net_value)}, total off ${rupees(c.gross_value)}` : ''}</p>
        </div>
        {c.status === 'approved' && <span className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-700"><CheckCircle2 className="size-4" /> Approved by {c.approved_by_name}</span>}
      </div>
      {groups.map((g) => (
        <div key={g} className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{g}</h3>
          {c.lines!.filter((l) => l.main_category === g).map((l) => <CountRow key={l.material_id} l={l} d={draft[l.material_id]} live={c.may_count} money={money} onChange={(patch) => setDraft((all) => ({ ...all, [l.material_id]: { ...all[l.material_id], ...patch } }))} />)}
        </div>
      ))}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {c.may_count && (
        <div className="sticky bottom-0 -mx-3 flex flex-wrap gap-2 border-t bg-background px-3 py-2 sm:-mx-4 sm:px-4">
          <Button className="h-11 flex-1 gap-2 font-semibold" disabled={save.isPending} onClick={() => save.mutate()}><Save className="size-4" /> {save.isPending ? 'Saving…' : 'Save count'}</Button>
          {c.may_approve && <Button variant="outline" className="h-11 flex-1 gap-2" disabled={approve.isPending} onClick={() => approve.mutate()}><CheckCircle2 className="size-4" /> Approve differences</Button>}
          <Button variant="ghost" className="h-11 text-muted-foreground" onClick={() => cancel.mutate()}>Cancel count</Button>
        </div>
      )}
    </section>
  )
}

function CountRow({ l, d, live, money, onChange }: { l: CountLine; d?: { counted: string; reason: CountReason | '' }; live: boolean; money: boolean; onChange: (p: Partial<{ counted: string; reason: CountReason | '' }>) => void }) {
  const counted = d?.counted ?? ''
  const diff = counted.trim() === '' ? null : Number(counted) - Number(l.book)
  return (
    <div className={cn('flex flex-col gap-2 rounded-lg border px-3 py-2 sm:flex-row sm:items-center', diff && 'border-orange-300 bg-orange-50/50 dark:border-orange-800 dark:bg-orange-950/20')}>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{l.material}</span>
        <span className="block text-xs text-muted-foreground">Book {n(l.book)} {l.unit}{diff ? ` · ${diff > 0 ? '+' : ''}${n(String(diff))} ${l.unit}` : ''}{money && l.difference_value && Number(l.difference_value) ? ` · ${rupees(l.difference_value)}` : ''}</span>
      </span>
      <span className="flex items-center gap-2">
        <Input inputMode="decimal" disabled={!live} value={counted} placeholder="Not counted" onChange={(e) => onChange({ counted: e.target.value })} className="h-12 w-32 text-right text-lg tabular-nums" aria-label={`Counted ${l.material}`} />
        <span className="w-10 text-sm text-muted-foreground">{l.unit}</span>
        {!!diff && (
          <select disabled={!live} value={d?.reason ?? ''} onChange={(e) => onChange({ reason: e.target.value as CountReason })} className="h-12 rounded-md border bg-background px-2 text-sm" aria-label={`Why ${l.material} differs`}>
            <option value="">Why?</option>
            {COUNT_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        )}
      </span>
    </div>
  )
}
