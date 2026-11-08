import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckCheck, ListTodo, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/ui/toast-notification'
import { PageError } from '@/components/dpr-page'
import { usePlanningProject } from '@/components/schedule/project-picker'
import { billDay } from '@/lib/billing'
import {
  closeSnag, deleteSnag, fetchSnags, raiseSnag, reopenSnag, snagFixed, SNAG_STATUS, updateSnag, type Snag, type SnagInput,
} from '@/lib/closeout'
import { apiErrorMessage } from '@/lib/logo-upload'
import { usePageTitle } from '@/lib/page-title'
import { fetchSites } from '@/lib/projects'
import { fetchLifecycle } from '@/lib/schedule'
import { useReadOnly } from '@/lib/trial'
import { cn } from '@/lib/utils'

// END-01: Site › Snag list. What still has to be put right before handover (and, after it, what the client reports
// in the defect period): where, what, who fixes it, by when. The site says "fixed"; the PM checks and closes it, or
// sends it back with the reason. The same snags are raised and fixed from WhatsApp (END-05).

const SELECT = 'h-9 w-full rounded-md border bg-background px-2 text-sm'
const FILTERS = [
  { key: 'pending', label: 'To do' },
  { key: 'open', label: 'Open' },
  { key: 'fixed', label: 'Fixed, to check' },
  { key: 'closed', label: 'Closed' },
  { key: '', label: 'All' },
] as const

export default function SnagsPage() {
  usePageTitle('Snag list')
  const projectId = usePlanningProject()
  const readOnly = useReadOnly()
  const [filter, setFilter] = React.useState<string>('pending')
  const [editing, setEditing] = React.useState<Snag | 'new' | null>(null)
  const query = useQuery({ queryKey: ['snags', projectId, filter], queryFn: () => fetchSnags({ projectId, status: filter }) })
  const data = query.data
  const pending = data ? data.counts.open + data.counts.fixed : 0
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="mx-auto flex w-full max-w-5xl min-w-0 flex-col gap-4 pb-8 sm:px-2">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="inline-flex size-10 items-center justify-center rounded-xl bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-200"><ListTodo className="size-5" /></span>
          <div>
            <div className="text-xs text-muted-foreground">Site</div>
            <h1 className="text-2xl leading-tight font-semibold tracking-tight">Snag list</h1>
          </div>
        </div>
        {!readOnly && <Button size="sm" className="gap-1.5" onClick={() => setEditing('new')}><Plus className="size-4" /> Add a snag</Button>}
      </header>
      <p className="text-sm text-muted-foreground">
        Walk every room before handover and list what to put right. The site can also send it on WhatsApp: “bedroom 2 tile chipped near the door”.
        {projectId && <> See the <Link className="underline underline-offset-2" to={`/planning/handover?project=${projectId}`}>handover checklist</Link>.</>}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const n = !data ? null : f.key === 'pending' ? pending : f.key === '' ? data.counts.open + data.counts.fixed + data.counts.closed : data.counts[f.key]
          return (
            <button key={f.key} type="button" onClick={() => setFilter(f.key)}
              className={cn('rounded-full border px-3 py-1 text-sm', filter === f.key ? 'border-primary bg-primary/10 font-medium' : 'hover:bg-muted/50')}>
              {f.label}{n !== null && <span className="ml-1 text-muted-foreground tabular-nums">{n}</span>}
            </button>
          )
        })}
      </div>

      {query.isError ? (
        <PageError message="The snags did not load." onRetry={() => query.refetch()} back={{ to: '/', label: 'Home' }} />
      ) : !data ? (
        <Skeleton className="h-48 w-full" />
      ) : data.snags.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          {filter === 'pending' ? 'Nothing left to put right.' : 'No snags here.'} “Add a snag” for each thing to fix: the place, what is wrong and who fixes it.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {data.snags.map((s) => (
            <SnagRow key={s.id} snag={s} showProject={!projectId} canManage={data.can_manage && !readOnly} readOnly={readOnly}
              overdue={s.status === 'open' && !!s.due_on && s.due_on < today} onEdit={() => setEditing(s)} />
          ))}
        </ul>
      )}
      <SnagDialog editing={editing} projectId={projectId} onClose={() => setEditing(null)} />
    </div>
  )
}

function SnagRow({ snag: s, showProject, canManage, readOnly, overdue, onEdit }: {
  snag: Snag; showProject: boolean; canManage: boolean; readOnly: boolean; overdue: boolean; onEdit: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [asking, setAsking] = React.useState<'fixed' | 'reopen' | null>(null)
  const [text, setText] = React.useState('')
  const act = useMutation({
    mutationFn: async (what: 'fixed' | 'close' | 'reopen' | 'delete') => {
      if (what === 'fixed') return snagFixed(s.id, text.trim())
      if (what === 'close') return closeSnag(s.id)
      if (what === 'reopen') return reopenSnag(s.id, text.trim())
      return deleteSnag(s.id)
    },
    onSuccess: (_r, what) => {
      queryClient.invalidateQueries({ queryKey: ['snags'] })
      queryClient.invalidateQueries({ queryKey: ['handover'] })
      setAsking(null)
      setText('')
      toast.success({ fixed: `${s.ref} marked fixed`, close: `${s.ref} closed`, reopen: `${s.ref} sent back`, delete: `${s.ref} removed` }[what])
    },
    onError: (e) => toast.error('Not saved', apiErrorMessage(e)),
  })
  const who = [s.trade, s.vendor_name].filter(Boolean).join(' · ')
  return (
    <li className="flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{s.ref}</span>
            <span className="font-medium">{s.place ? `${s.place}: ` : ''}{s.description}</span>
            <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', SNAG_STATUS[s.status].tone)}>{SNAG_STATUS[s.status].label}</span>
            {s.phase === 'defects' && <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[11px] font-semibold text-orange-800 dark:bg-orange-950 dark:text-orange-200">Defect period</span>}
            {s.found_by === 'client' && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold">Client</span>}
          </p>
          <p className="text-xs text-muted-foreground">
            {[showProject && s.project_name, s.site_name, who && `fixes: ${who}`, s.due_on && `by ${billDay(s.due_on)}`, s.raised_by_name && `raised by ${s.raised_by_name}`].filter(Boolean).join(' · ')}
            {overdue && <span className="ml-1 font-medium text-red-700 dark:text-red-300">· past its day</span>}
          </p>
          {s.fixed_note && s.status !== 'open' && <p className="text-xs">Fix: {s.fixed_note}</p>}
          {s.reopened_note && s.status === 'open' && <p className="text-xs text-red-700 dark:text-red-300">Sent back: {s.reopened_note}</p>}
        </div>
        {!readOnly && (
          <div className="flex flex-wrap gap-1.5">
            {s.status === 'open' && <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setAsking('fixed')}><Check className="size-3.5" /> Fixed</Button>}
            {canManage && s.status !== 'closed' && <Button size="sm" variant="outline" className="gap-1.5" disabled={act.isPending} onClick={() => act.mutate('close')}><CheckCheck className="size-3.5" /> {s.status === 'fixed' ? 'Checked, close' : 'Close'}</Button>}
            {canManage && s.status === 'fixed' && <Button size="sm" variant="ghost" className="gap-1.5" onClick={() => setAsking('reopen')}><RotateCcw className="size-3.5" /> Not ok</Button>}
            {s.status !== 'closed' && <Button size="sm" variant="ghost" aria-label={`Edit ${s.ref}`} onClick={onEdit}><Pencil className="size-3.5" /></Button>}
            {canManage && s.status === 'open' && <Button size="sm" variant="ghost" aria-label={`Remove ${s.ref}`} disabled={act.isPending} onClick={() => act.mutate('delete')}><Trash2 className="size-3.5" /></Button>}
          </div>
        )}
      </div>
      {asking && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (asking === 'fixed' || text.trim()) act.mutate(asking) }}>
          <Input autoFocus className="h-8 max-w-md flex-1" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={asking === 'fixed' ? 'What was done (optional): replaced 2 tiles' : 'What is still wrong: grout colour differs'} />
          <Button size="sm" type="submit" disabled={act.isPending || (asking === 'reopen' && !text.trim())}>{asking === 'fixed' ? 'Mark fixed' : 'Send back'}</Button>
          <Button size="sm" type="button" variant="ghost" onClick={() => { setAsking(null); setText('') }}>Cancel</Button>
        </form>
      )}
    </li>
  )
}

function SnagDialog({ editing, projectId, onClose }: { editing: Snag | 'new' | null; projectId: string | null; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const existing = editing && editing !== 'new' ? editing : null
  const [form, setForm] = React.useState<Record<string, string>>({})
  const project = existing?.project_id ?? form.project_id ?? projectId ?? ''
  const projects = useQuery({ queryKey: ['lifecycle'], queryFn: fetchLifecycle, enabled: !!editing && !projectId && !existing })
  const sites = useQuery({ queryKey: ['sites', project], queryFn: () => fetchSites(project), enabled: !!editing && !!project })
  React.useEffect(() => {
    if (!editing) return
    setForm({
      project_id: existing?.project_id ?? projectId ?? '', description: existing?.description ?? '', place: existing?.place ?? '',
      site_id: existing?.site_id ?? '', trade: existing?.trade ?? '', due_on: existing?.due_on ?? '', found_by: existing?.found_by ?? 'us',
    })
  }, [editing, existing, projectId])
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const save = useMutation({
    mutationFn: () => {
      const body: SnagInput = {
        description: form.description.trim(), place: form.place.trim() || null, site_id: form.site_id || null,
        trade: form.trade.trim() || null, due_on: form.due_on || null, found_by: form.found_by === 'client' ? 'client' : 'us',
      }
      return existing ? updateSnag(existing.id, body) : raiseSnag(project, body)
    },
    onSuccess: (s) => {
      queryClient.invalidateQueries({ queryKey: ['snags'] })
      queryClient.invalidateQueries({ queryKey: ['handover'] })
      toast.success(`${s.ref} saved`)
      onClose()
    },
    onError: (e) => toast.error('Could not save the snag', apiErrorMessage(e)),
  })
  const ready = !!project && !!form.description?.trim()
  return (
    <Dialog open={!!editing} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{existing ? `Edit ${existing.ref}` : 'Add a snag'}</DialogTitle>
          <DialogDescription>One thing to put right. The site marks it fixed; a manager checks and closes it.</DialogDescription>
        </DialogHeader>
        <form id="snag-form" className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (ready) save.mutate() }}>
          {!existing && !projectId && (
            <div className="grid gap-1 sm:col-span-2">
              <Label htmlFor="sn-project">Project</Label>
              <select id="sn-project" className={SELECT} value={form.project_id ?? ''} onChange={set('project_id')} required>
                <option value="">Pick the project</option>
                {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}
          <div className="grid gap-1 sm:col-span-2">
            <Label htmlFor="sn-what">What is wrong</Label>
            <Input id="sn-what" required placeholder="Tile chipped near the door" value={form.description ?? ''} onChange={set('description')} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="sn-place">Where</Label>
            <Input id="sn-place" placeholder="Bedroom 2, first floor" value={form.place ?? ''} onChange={set('place')} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="sn-site">Site</Label>
            <select id="sn-site" className={SELECT} value={form.site_id ?? ''} onChange={set('site_id')}>
              <option value="">—</option>
              {sites.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="sn-trade">Who fixes it</Label>
            <Input id="sn-trade" placeholder="Tiler, plumber, electrician…" value={form.trade ?? ''} onChange={set('trade')} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="sn-due">Fix by</Label>
            <Input id="sn-due" type="date" value={form.due_on ?? ''} onChange={set('due_on')} />
          </div>
          <div className="grid gap-1 sm:col-span-2">
            <Label htmlFor="sn-found">Found by</Label>
            <select id="sn-found" className={SELECT} value={form.found_by ?? 'us'} onChange={set('found_by')}>
              <option value="us">Our walk-round</option>
              <option value="client">The client</option>
            </select>
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="snag-form" disabled={save.isPending || !ready}>{save.isPending ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
